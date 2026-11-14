"""Co-Scientist: hypothesis generation for one explored dataset.

Two agents, run one after the other in a background thread:

1. **Generator** digs through the dataset: the probe and card, queries on
   the data sample (distributions, group summaries, rows, records, signal
   statistics), the papers and FDA devices the catalog links to it, and the
   web. It submits exactly 10 hypotheses, each with the observations and
   citations it rests on and a plan to test it.
2. **Reviewer** starts fresh (no access to the generator's reasoning), with
   the same tools to check claims. It scores every hypothesis for
   feasibility, value, novelty and rigor, writes a critique, and picks the 5
   best as a diverse set.

Runs are stored (``hypothesis_runs``) with a progress log, so the page can
show progress while it works and the result afterwards. Both agents use the
planner model (DATASETS_PLANNER_MODEL). Tools are the explore chat's
read-only tools, so the agents can't change the page or the data.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

from .explore import CHAT_TOOLS, ExploreChat, ExploreManager
from .explore_sources import SourceError
from .store import now_iso

log = logging.getLogger(__name__)

N_GENERATE, N_SELECT = 10, 5
SCORES = ("feasibility", "value", "novelty", "rigor")

_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}
HYPOTHESIS = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "statement", "rationale", "evidence", "exposure", "outcome",
                 "covariates", "test_plan", "data_gaps", "literature"],
    "properties": {
        "title": _STR,
        "statement": {"type": "string", "description": "One falsifiable sentence."},
        "rationale": _STR,
        "evidence": {**_STRS, "description": "Observations from the tools, with numbers and n."},
        "exposure": {"type": "string", "description": "Field/label/channel, or '' if n/a."},
        "outcome": {"type": "string", "description": "Field/label/channel, or '' if n/a."},
        "covariates": _STRS,
        "test_plan": {"type": "string", "description": "Analysis to test it on the full dataset."},
        "data_gaps": {"type": "string", "description": "What this dataset lacks, or ''."},
        "literature": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["citation", "url"],
            "properties": {"citation": _STR, "url": _STR}}},
    },
}
SUBMIT_HYPOTHESES = {
    "name": "submit_hypotheses", "strict": True,
    "description": f"Submit exactly {N_GENERATE} hypotheses. Call once, when done investigating.",
    "input_schema": {"type": "object", "additionalProperties": False, "required": ["hypotheses"],
                     "properties": {"hypotheses": {"type": "array", "items": HYPOTHESIS}}},
}
SUBMIT_REVIEW = {
    "name": "submit_review", "strict": True,
    "description": f"Submit scores for all {N_GENERATE} hypotheses and the {N_SELECT} you select.",
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "required": ["reviews", "selected", "summary"],
        "properties": {
            "reviews": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["number", *SCORES, "critique"],
                "properties": {"number": {"type": "integer"},
                               **{k: {"type": "integer", "description": "1 (poor) to 5 (excellent)"}
                                  for k in SCORES},
                               "critique": _STR}}},
            "selected": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["number", "why"],
                "properties": {"number": {"type": "integer"}, "why": _STR}}},
            "summary": _STR,
        },
    },
}

GENERATOR_SYSTEM = f"""You are a research scientist (epidemiology, biostatistics, \
biomedical data science) generating hypotheses from one dataset for a researcher.

Investigate before proposing. Use describe_data, then look at the key fields: \
distributions, group summaries, rows, records and signal statistics. Check the \
papers our catalog links to the dataset (publications), linked FDA devices \
(fda_devices), and the web where useful, so you know what has been studied.

Then submit exactly {N_GENERATE} distinct hypotheses with submit_hypotheses. Each should:
- be testable with this dataset (name the real fields, labels or channels), or \
state precisely what extra data it needs in data_gaps;
- rest on what you observed (numbers you computed, with n) and/or literature the \
tools returned; observations from a sample are leads, not results, so say so;
- add something beyond the dataset's primary published finding.
Cover different kinds: associations, effect modification or subgroups, \
signal/image features, measurement and label quality, bias and generalizability, \
prognosis. Never invent fields, values or citations; cite only papers the tools \
returned, with their URL."""

REVIEWER_SYSTEM = f"""You are a skeptical senior reviewer (epidemiologist and \
biostatistician) on a study committee. You get {N_GENERATE} hypotheses proposed for \
one dataset. Score each 1-5 on:
- feasibility: testable with this dataset's fields, sample size, labels and access, \
without data it lacks;
- value: scientific or clinical importance if true;
- novelty: against the linked and published literature (check with publications \
or web_search when unsure);
- rigor: falsifiable, clearly defined, with confounding and bias addressable.
Use the data tools to check claims that matter (group sizes, whether a field \
exists, whether a quoted number holds). Write a short, specific critique for \
each. Then select the {N_SELECT} best as a set: strong on all four, diverse in kind, \
none resting on a misread of the data. Submit with submit_review (numbers are \
1-{N_GENERATE} in the order given) and a two-sentence summary of the selection."""


def _validate_hypotheses(inp: dict) -> str | None:
    hs = inp.get("hypotheses") or []
    if len(hs) != N_GENERATE:
        return f"submit exactly {N_GENERATE} hypotheses (got {len(hs)})"
    if len({h.get("title", "").strip().lower() for h in hs}) < N_GENERATE:
        return "hypothesis titles must be distinct"
    return None


def _validate_review(inp: dict) -> str | None:
    nums = {r.get("number") for r in inp.get("reviews") or []}
    if nums != set(range(1, N_GENERATE + 1)):
        return f"review every hypothesis exactly once, numbered 1-{N_GENERATE}"
    for r in inp["reviews"]:
        if any(not isinstance(r.get(k), int) or not 1 <= r[k] <= 5 for k in SCORES):
            return "scores must be integers from 1 to 5"
    sel = [s.get("number") for s in inp.get("selected") or []]
    if len(sel) != N_SELECT or len(set(sel)) != N_SELECT or not set(sel) <= nums:
        return f"select exactly {N_SELECT} distinct hypotheses by number"
    return None


def run_agent(client, settings, *, system: str, user: str, submit: dict,
              validate: Callable[[dict], str | None], tool_fn: Callable[[str, dict], Any],
              log_: Callable[[str], None], max_turns: int = 24) -> dict:
    """Tool loop until the agent calls `submit` with valid input."""
    from .crawler import WEB_TOOLS, _create, _tool_result
    tools = [*CHAT_TOOLS, *WEB_TOOLS, submit]
    msgs: list[dict] = [{"role": "user", "content": user}]
    for _ in range(max_turns):
        resp = _create(client, settings, model=settings.planner_model, system=system,
                       tools=tools, output_config={"effort": settings.planner_effort},
                       messages=msgs)
        msgs.append({"role": "assistant", "content": resp.content})
        for b in resp.content:
            if b.type == "server_tool_use":
                q = (b.input or {}).get("query") or (b.input or {}).get("url") or ""
                log_(f"{b.name.replace('_', ' ')}: {str(q)[:90]}")
        if resp.stop_reason == "refusal":
            raise SourceError("the request was declined")
        if resp.stop_reason == "pause_turn":
            continue
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            msgs.append({"role": "user", "content": f"Call {submit['name']} now with your answer."})
            continue
        results, done = [], None
        for b in uses:
            args = b.input or {}
            if b.name == submit["name"]:
                err = validate(args)
                results.append(_tool_result(b.id, {"error": err} if err else "received", bool(err)))
                if not err:
                    done = args
                continue
            log_(f"{b.name}" + (f" ({', '.join(f'{k}={v}' for k, v in args.items())[:90]})"
                                if args else ""))
            try:
                out = tool_fn(b.name, args)
                results.append(_tool_result(b.id, json.dumps(out, default=str)[:15000]))
            except Exception as exc:
                results.append(_tool_result(b.id, {"error": str(exc)[:300]}, True))
        if done is not None:
            return done
        msgs.append({"role": "user", "content": results})
    raise SourceError("the agent ran out of steps before submitting")


class CoScientist:
    def __init__(self, explorer: ExploreManager):
        self.explorer = explorer
        self.store = explorer.store
        self.tools = ExploreChat(explorer)
        self._jobs: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        with self.store._write() as c:     # threads don't survive a restart
            c.execute("UPDATE hypothesis_runs SET status = 'failed', error = 'interrupted by a"
                      " restart', finished_at = ? WHERE status IN ('generating', 'reviewing')",
                      (now_iso(),))

    # -- storage
    def _update(self, run_id: int, **fields) -> None:
        for k in ("log", "candidates", "review"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k])
        with self.store._write() as c:
            c.execute(f"UPDATE hypothesis_runs SET {', '.join(f'{k} = ?' for k in fields)}"
                      " WHERE id = ?", [*fields.values(), run_id])

    def latest(self, ds_id: str) -> dict | None:
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM hypothesis_runs WHERE dataset_id = ?"
                            " ORDER BY id DESC LIMIT 1", (ds_id,)).fetchone()
            n = c.execute("SELECT COUNT(*) FROM hypothesis_runs WHERE dataset_id = ?"
                          " AND status = 'ready'", (ds_id,)).fetchone()[0]
        if not row:
            return None
        d = dict(row)
        for k in ("log", "candidates", "review"):
            d[k] = json.loads(d[k]) if d[k] else None
        d["runs_ready"] = n
        d["busy"] = self.busy(ds_id)
        if d["candidates"] and d["review"]:
            d["selected"] = self.selection(d["candidates"], d["review"])
        return d

    @staticmethod
    def selection(cands: list[dict], review: dict) -> list[dict]:
        by_num = {r["number"]: r for r in review.get("reviews") or []}
        out = []
        for rank, s in enumerate(review.get("selected") or [], 1):
            i = s["number"]
            r = by_num.get(i, {})
            out.append({**cands[i - 1], "number": i, "rank": rank, "why": s.get("why"),
                        "scores": {k: r.get(k) for k in SCORES}, "critique": r.get("critique")})
        return out

    # -- jobs
    def busy(self, ds_id: str) -> bool:
        t = self._jobs.get(ds_id)
        return bool(t and t.is_alive())

    def start(self, ds_id: str) -> int:
        if self.explorer.client_factory is None:
            raise SourceError("Co-Scientist needs ANTHROPIC_API_KEY")
        ex = self.explorer.get(ds_id)
        if not ex or not ex.get("spec"):
            raise SourceError("build the explore page first")
        with self._lock:
            if self.busy(ds_id):
                raise RuntimeError("already running")
            with self.store._write() as c:
                run_id = c.execute(
                    "INSERT INTO hypothesis_runs (dataset_id, status, model, started_at)"
                    " VALUES (?, 'generating', ?, ?)",
                    (ds_id, self.explorer.settings.planner_model, now_iso())).lastrowid
            t = threading.Thread(target=self._run_safe, args=(ds_id, run_id), daemon=True,
                                 name=f"coscientist-{ds_id}")
            self._jobs[ds_id] = t
            t.start()
        return run_id

    def _run_safe(self, ds_id: str, run_id: int) -> None:
        try:
            self.run(ds_id, run_id)
        except Exception as exc:
            log.exception("co-scientist run %s failed", run_id)
            self._update(run_id, status="failed", finished_at=now_iso(),
                         error=str(exc)[:800] if isinstance(exc, SourceError)
                         else f"{type(exc).__name__}: {str(exc)[:500]}")

    def run(self, ds_id: str, run_id: int) -> dict:
        m = self.explorer
        ds = m.store.get_dataset(ds_id)
        ex = m.get(ds_id) or {}
        lines: list[str] = []

        def log_(msg: str) -> None:
            lines.append(f"{now_iso()[11:19]} {msg}")
            self._update(run_id, log=lines[-80:])

        card = {k: ds.get(k) for k in ("title", "url", "source", "description", "labels",
                                       "conditions", "modalities", "n_subjects", "access_type",
                                       "citation", "n_articles")}
        context = (f"Dataset card:\n{json.dumps(card, default=str)}\n\nExplore page views: "
                   + ", ".join(p["title"] for p in (ex.get("spec") or {}).get("panels", [])))
        client = m.client_factory(m.settings)
        tool_fn = lambda name, args: self.tools._tool(ds_id, name, args)  # noqa: E731

        log_("Generator: investigating the data and literature…")
        gen = run_agent(client, m.settings, system=GENERATOR_SYSTEM,
                        user=context + f"\n\nInvestigate, then submit {N_GENERATE} hypotheses.",
                        submit=SUBMIT_HYPOTHESES, validate=_validate_hypotheses,
                        tool_fn=tool_fn, log_=log_)
        cands = gen["hypotheses"]
        log_(f"Generator: submitted {len(cands)} hypotheses")
        self._update(run_id, status="reviewing", candidates=cands)

        log_("Reviewer: scoring feasibility, value, novelty and rigor…")
        listing = "\n\n".join(f"#{i}. {h['title']}\n{json.dumps(h)}" for i, h in enumerate(cands, 1))
        review = run_agent(client, m.settings, system=REVIEWER_SYSTEM,
                           user=f"{context}\n\nHypotheses:\n\n{listing}",
                           submit=SUBMIT_REVIEW, validate=_validate_review,
                           tool_fn=tool_fn, log_=log_)
        log_(f"Reviewer: selected #{', #'.join(str(s['number']) for s in review['selected'])}")
        self._update(run_id, status="ready", review=review, finished_at=now_iso())
        return review
