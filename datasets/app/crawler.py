"""LLM-driven crawl: a planner call, then a swarm of Claude agents.

Flow for one crawl session:

1. **Plan** (one structured-output call): turn the user's query — or, for a
   broad crawl, a target condition — into canonical conditions (+ synonyms
   and FDA device-name terms for the 510(k) count) and a handful of search
   *angles* (repository-specific or modality-specific hunts).
2. **Swarm**: ``swarm_size`` agents run concurrently, each taking one angle.
   Each agent is a manual tool-use loop with Anthropic's server-side
   ``web_search`` / ``web_fetch`` plus three client tools we execute:
   ``record_dataset`` (upsert a dataset card), ``check_catalog`` (what do we
   already have?) and ``probe_url`` (is this link a real flat file?).
3. **Download**: every recorded open-access dataset's direct file links are
   fetched in the background (``download.fetch_dataset_files``).

A crawl is bounded by wall-clock (``minutes``); agents check the deadline
between turns and stop cleanly. Broad crawls walk the condition directory in
510(k) order, re-planning per condition, until the deadline.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from . import download, fda
from .config import Settings
from .store import ACCESS_TYPES, Store

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5,
     "max_content_tokens": 20000},
]

RECORD_DATASET_TOOL = {
    "name": "record_dataset",
    "description": (
        "Save one dataset to the catalog. Call this once per distinct dataset as soon as "
        "you have verified its landing page. `url` must be the dataset's canonical landing "
        "page (not a search result or a paper). Put only direct links to flat files "
        "(csv/tsv/json/parquet/xlsx/zip/tar.gz/nii.gz/edf/dcm/...) in `download_urls`; "
        "leave it empty when files sit behind a login, DUA, or request form, and explain "
        "how to get access in `access_instructions` instead."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "url", "source", "description", "conditions", "modalities",
                     "labels", "size", "n_subjects", "file_formats", "license",
                     "access_type", "access_instructions", "download_urls", "citation",
                     "tags"],
        "properties": {
            "title": {"type": "string"},
            "url": {"type": "string", "description": "Canonical landing page URL."},
            "source": {"type": "string",
                       "description": "Host/repository, e.g. PhysioNet, TCIA, Kaggle, "
                                      "Zenodo, OpenNeuro, Grand Challenge, a lab site."},
            "description": {"type": "string",
                            "description": "2-4 sentences: what it contains and how it "
                                           "was collected."},
            "conditions": {"type": "array", "items": {"type": "string"},
                           "description": "Canonical condition names (lowercase, e.g. "
                                          "'multiple sclerosis', 'pneumothorax')."},
            "modalities": {"type": "array", "items": {"type": "string"},
                           "description": "e.g. 'mri', 'ct', 'chest x-ray', 'ecg', 'ehr', "
                                          "'pathology', 'fundus', 'genomics'."},
            "labels": {"type": "string",
                       "description": "What ground truth/annotations exist (segmentation "
                                      "masks, diagnoses, clinical variables...). Empty if "
                                      "unknown."},
            "size": {"type": "string", "description": "e.g. '12 GB', '3,000 images'."},
            "n_subjects": {"type": "string"},
            "file_formats": {"type": "array", "items": {"type": "string"}},
            "license": {"type": "string"},
            "access_type": {"type": "string", "enum": list(ACCESS_TYPES)},
            "access_instructions": {
                "type": "string",
                "description": "Step-by-step instructions a human follows to obtain the "
                               "data (account, training such as CITI, DUA, request "
                               "form, tools like aws s3/wget/datalad). Always fill."},
            "download_urls": {"type": "array", "items": {"type": "string"}},
            "citation": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    },
}

CHECK_CATALOG_TOOL = {
    "name": "check_catalog",
    "description": "Search the datasets already in our catalog (title + url). Use it "
                   "before recording something you suspect we already have.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}

PROBE_URL_TOOL = {
    "name": "probe_url",
    "description": "Issue a GET (headers only) against a URL and report content type, "
                   "size and whether it is a directly downloadable flat file or an HTML "
                   "landing/login page. Use it to verify candidate download links.",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
}

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "conditions", "modalities", "angles"],
    "properties": {
        "summary": {"type": "string"},
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "display", "synonyms", "fda_terms"],
                "properties": {
                    "name": {"type": "string"},
                    "display": {"type": "string"},
                    "synonyms": {"type": "array", "items": {"type": "string"}},
                    "fda_terms": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "modalities": {"type": "array", "items": {"type": "string"}},
        "angles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["focus", "instructions"],
                "properties": {
                    "focus": {"type": "string"},
                    "instructions": {"type": "string"},
                },
            },
        },
    },
}

PLANNER_SYSTEM = """You plan web crawls that find medical datasets for training and \
validating software-as-a-medical-device (SaMD) models.

Given a request, return:
- conditions: the canonical disease/condition(s) it targets. `name` is lowercase and \
unabbreviated ("multiple sclerosis", not "MS"). `synonyms` are the abbreviations and \
alternate names people search with. `fda_terms` are 2-6 short phrases likely to appear \
in the *device name* of FDA 510(k)-cleared devices for this condition (e.g. for \
pneumothorax: "pneumothorax", "chest x-ray triage"); avoid generic words.
- modalities the request implies (mri, ct, chest x-ray, ecg, eeg, ehr, pathology, ...).
- angles: {n} distinct, non-overlapping search strategies for {n} parallel agents. \
Spread them across repositories (PhysioNet, TCIA, OpenNeuro, Grand Challenge / MICCAI \
challenges, Kaggle, Zenodo, figshare, Mendeley Data, Synapse, Hugging Face, UK Biobank / \
dbGaP-style controlled access, NIH/NLM, university lab pages, papers' data \
availability statements) and data types, weighted toward what the request asks for. \
`instructions` tells the agent concretely what to look for and where."""

WORKER_SYSTEM = """You are a research agent building a catalog of medical datasets for \
people developing software-as-a-medical-device. Use web_search and web_fetch to find \
real, existing datasets, verify each one on its own landing page, and save each with \
record_dataset.

Rules:
- Only record datasets you have verified exist (you fetched the landing page or an \
authoritative page describing it). Never invent URLs, sizes, licenses or counts; leave \
a field empty if you could not verify it.
- One record per dataset (not per paper or per file). If a challenge has several \
releases, record each distinct release.
- Access: `open` = anyone can download without an account; `registration` = free \
account/click-through; `credentialed` = identity verification or training (e.g. \
PhysioNet credentialed + CITI); `dua` = signed data use agreement; `request` = \
application reviewed by the data owner; else `unknown`. Always write concrete \
access_instructions.
- download_urls: only direct links to flat files you have reason to believe download \
without login (use probe_url to check when unsure). Prefer the full archive or the main \
tables over hundreds of individual files; at most 10.
- Skip anything already in the catalog unless you have materially better information \
(then record it again with the same landing URL to merge).
- Work until you've exhausted your angle, then reply with a one-paragraph summary of \
what you recorded. Be efficient: don't re-fetch pages you've read."""


@dataclass
class CrawlContext:
    crawl_id: int
    store: Store
    settings: Settings
    deadline: float
    cancel: threading.Event
    on_dataset: Callable[[str, bool], None]
    usage_lock: threading.Lock = field(default_factory=threading.Lock)

    def time_left(self) -> float:
        return self.deadline - time.monotonic()

    def done(self) -> bool:
        return self.cancel.is_set() or self.time_left() <= 0

    def log(self, msg: str) -> None:
        log.info("crawl %s: %s", self.crawl_id, msg)
        self.store.log_crawl(self.crawl_id, msg)

    def add_usage(self, usage: Any) -> None:
        if usage is None:
            return
        self.store.add_usage(self.crawl_id, getattr(usage, "input_tokens", 0) or 0,
                             getattr(usage, "output_tokens", 0) or 0)


def make_client(settings: Settings):
    import anthropic
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _create(client, settings: Settings, **kw):
    """One Messages API call with our defaults (adaptive thinking, auto
    prompt-caching, server-side refusal fallback)."""
    params: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": 16000,
        "thinking": {"type": "adaptive"},
        "cache_control": {"type": "ephemeral"},
        **kw,
    }
    if settings.fallbacks and settings.fallbacks != "off":
        params["betas"] = [FALLBACK_BETA]
        params["fallbacks"] = settings.fallbacks
    return client.beta.messages.create(**params)


# ---------------------------------------------------------------- planning
def plan_crawl(client, ctx: CrawlContext, request: str, n_angles: int) -> dict:
    resp = _create(
        client, ctx.settings,
        system=PLANNER_SYSTEM.replace("{n}", str(n_angles)),
        output_config={"effort": ctx.settings.planner_effort,
                       "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        messages=[{"role": "user", "content": request}],
    )
    ctx.add_usage(getattr(resp, "usage", None))
    if resp.stop_reason == "refusal":
        raise RuntimeError("planner request was declined")
    text = next(b.text for b in resp.content if b.type == "text")
    plan = json.loads(text)
    plan["angles"] = plan["angles"][:n_angles] or [
        {"focus": "general", "instructions": request}]
    return plan


def register_plan_conditions(store: Store, plan: dict, refresh_fda: bool = True) -> None:
    for c in plan.get("conditions", []):
        key = store.upsert_condition(c["name"], c.get("display"), c.get("synonyms", []),
                                     c.get("fda_terms", []))
        cond = store.get_condition(key)
        if refresh_fda and cond and cond["fda_510k_count"] is None:
            fda.refresh_condition(store, key)


# ---------------------------------------------------------------- one agent
def _tool_result(tool_use_id: str, payload: Any, is_error: bool = False) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id,
            "content": json.dumps(payload) if not isinstance(payload, str) else payload,
            "is_error": is_error}


def _valid_record(rec: Any) -> str | None:
    if not isinstance(rec, dict):
        return "input must be an object"
    url = rec.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return "url must be an absolute http(s) URL"
    if not str(rec.get("title", "")).strip():
        return "title is required"
    for f in ("conditions", "modalities", "file_formats", "download_urls", "tags"):
        if f in rec and not isinstance(rec[f], list):
            return f"{f} must be a list"
    return None


def run_client_tool(ctx: CrawlContext, name: str, args: dict, found_by: str) -> tuple[Any, bool]:
    """Execute one client-side tool. Returns (result payload, is_error)."""
    if name == "record_dataset":
        err = _valid_record(args)
        if err:
            return {"error": err}, True
        ds_id, is_new = ctx.store.upsert_dataset(args, found_by=found_by)
        ctx.store.add_crawl_hit(ctx.crawl_id, ds_id, is_new)
        ctx.on_dataset(ds_id, is_new)
        ctx.log(f"{'new' if is_new else 'updated'}: {args.get('title', '')[:90]}")
        return {"id": ds_id, "status": "new" if is_new else "merged with existing"}, False
    if name == "check_catalog":
        hits = ctx.store.known_for_prompt([str(args.get("query", ""))], limit=25)
        return {"matches": hits}, False
    if name == "probe_url":
        url = str(args.get("url", ""))
        return download.probe(url, allow_private=ctx.settings.allow_private_hosts), False
    return {"error": f"unknown tool {name}"}, True


def run_agent(client, ctx: CrawlContext, task: str, label: str) -> int:
    """Manual tool-use loop for one swarm member. Returns turns used."""
    tools = [*WEB_TOOLS, RECORD_DATASET_TOOL, CHECK_CATALOG_TOOL, PROBE_URL_TOOL]
    messages: list[dict] = [{"role": "user", "content": task}]
    turns = 0
    while turns < ctx.settings.max_turns_per_agent:
        if ctx.done():
            ctx.log(f"[{label}] stopping: {'cancelled' if ctx.cancel.is_set() else 'time up'}")
            break
        turns += 1
        try:
            resp = _create(client, ctx.settings, system=WORKER_SYSTEM, tools=tools,
                           output_config={"effort": ctx.settings.worker_effort},
                           messages=messages)
        except Exception as exc:  # network / API errors end this agent only
            ctx.log(f"[{label}] API error: {type(exc).__name__}: {str(exc)[:200]}")
            break
        ctx.add_usage(getattr(resp, "usage", None))
        # Append the full content (thinking + server tool blocks) unchanged.
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "refusal":
            ctx.log(f"[{label}] request declined; agent stopped")
            break
        if resp.stop_reason == "pause_turn":
            continue  # server-side tool loop hit its limit; resend to resume
        if resp.stop_reason == "tool_use":
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                try:
                    payload, is_err = run_client_tool(ctx, block.name, block.input or {},
                                                      found_by=label)
                except Exception as exc:
                    payload, is_err = {"error": str(exc)[:300]}, True
                results.append(_tool_result(block.id, payload, is_err))
            remaining = max(0, int(ctx.time_left() // 60))
            messages.append({"role": "user", "content": results + [
                {"type": "text", "text": f"({remaining} min left in this crawl session.)"}]})
            continue
        if resp.stop_reason == "max_tokens":
            # The turn may end mid tool_use; resuming would need a synthetic
            # result, so end this agent (records so far are already saved).
            ctx.log(f"[{label}] hit max_tokens; agent stopped")
            break
        summary = " ".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
        ctx.log(f"[{label}] finished: {summary[:300]}")
        break
    return turns


def build_task(request: str, plan: dict, angle: dict, known: list[dict]) -> str:
    conds = ", ".join(c["name"] for c in plan.get("conditions", [])) or "(unspecified)"
    known_txt = "\n".join(f"- {k['title']} — {k['url']}" for k in known) or "(none yet)"
    return (f"Request: {request}\n"
            f"Target condition(s): {conds}\n"
            f"Modalities: {', '.join(plan.get('modalities', [])) or 'any'}\n\n"
            f"Your angle: {angle['focus']}\n{angle['instructions']}\n\n"
            f"Already in the catalog (don't re-record unless you can add information):\n"
            f"{known_txt}")


# ---------------------------------------------------------------- swarm
def run_swarm(client, ctx: CrawlContext, request: str) -> dict:
    ctx.log(f"planning: {request}")
    plan = plan_crawl(client, ctx, request, ctx.settings.swarm_size)
    ctx.store.update_crawl(ctx.crawl_id, plan=plan)
    register_plan_conditions(ctx.store, plan)
    terms = [request] + [c["name"] for c in plan.get("conditions", [])]
    known = ctx.store.known_for_prompt(terms)
    ctx.log(f"plan: {plan.get('summary', '')[:200]} — {len(plan['angles'])} agents")
    with ThreadPoolExecutor(max_workers=len(plan["angles"]),
                            thread_name_prefix=f"crawl{ctx.crawl_id}") as pool:
        futs = [pool.submit(run_agent, client, ctx, build_task(request, plan, a, known),
                            f"agent{i + 1}:{a['focus'][:40]}")
                for i, a in enumerate(plan["angles"])]
        for f in futs:
            f.result()
    return plan


def broad_targets(store: Store, seed: list[dict]) -> list[str]:
    """Conditions for a broad crawl, most 510(k) clearances first; conditions
    with fewer datasets break ties so coverage spreads out."""
    for s in seed:
        store.upsert_condition(s["name"], s.get("display"), s.get("synonyms", []),
                               s.get("fda_terms", []))
    ranked = store.conditions_ranked()
    for r in ranked:
        if r["fda_510k_count"] is None:
            fda.refresh_condition(store, r["name"])
    ranked = store.conditions_ranked()
    ranked.sort(key=lambda r: (-(r["fda_510k_count"] or 0), r["n_datasets"]))
    return [r["display"] for r in ranked]


def run_broad(client, ctx: CrawlContext, seed: list[dict]) -> None:
    targets = broad_targets(ctx.store, seed)
    ctx.log(f"broad crawl over {len(targets)} conditions (510(k) order)")
    for cond in targets:
        if ctx.done():
            break
        try:
            run_swarm(client, ctx, f"Public and access-controlled datasets for {cond} "
                                    "(any modality) suitable for training or validating "
                                    "SaMD / AI medical-device algorithms")
        except Exception as exc:  # one bad condition shouldn't end the session
            ctx.log(f"{cond}: swarm failed: {type(exc).__name__}: {str(exc)[:200]}")
