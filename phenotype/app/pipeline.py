"""Job execution: search -> screen -> snowball -> extract -> grade -> report.

Every stage writes progress to the store so the status page can show where a
job is; literature and model failures in one record never sink the job.
"""
from __future__ import annotations

import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from . import catalog as C
from .compile import omop_sql, pseudocode
from .config import Settings
from .extract import extract, screen, suggest_titles
from .grading import Context, candidate_dict, rank
from .literature import Literature, europepmc_query, merge, norm_title, pubmed_query
from .mailer import send_report
from .providers import ChatModel, ModelError, build_model, parse_spec
from .report import render_report
from .schema import Study
from .store import Store

log = logging.getLogger("phenotype")


@dataclass
class JobSpec:
    condition: str
    synonyms: list[str] = field(default_factory=list)
    intended_use: str = "prevalence"
    data_types: list[str] = field(default_factory=lambda: ["claims"])
    coding_era: str = "icd10"
    country: str = ""
    expected_prevalence: float | None = None
    max_records: int = 150
    max_extract: int = 25
    snowball: bool = True
    model_suggestions: bool = True
    email: str = ""
    notes: str = ""

    def validate(self, settings: Settings) -> None:
        self.condition = " ".join(self.condition.split())[:120]
        if len(self.condition) < 3:
            raise ValueError("a condition is required (e.g. 'multiple sclerosis')")
        self.synonyms = [" ".join(s.split())[:80] for s in self.synonyms if s and s.strip()][:8]
        if self.intended_use not in C.INTENDED_USES:
            raise ValueError(f"intended use must be one of {list(C.INTENDED_USES)}")
        self.data_types = [d for d in self.data_types if d in C.DATA_TYPES] or ["claims"]
        if self.coding_era not in C.CODING_ERAS:
            raise ValueError(f"coding era must be one of {list(C.CODING_ERAS)}")
        self.country = self.country.strip()[:60]
        if self.expected_prevalence is not None:
            p = float(self.expected_prevalence)
            if not 0 < p < 1:
                raise ValueError("expected prevalence is a proportion between 0 and 1 (e.g. 0.003)")
            self.expected_prevalence = p
        if not 10 <= self.max_records <= settings.max_records_cap:
            raise ValueError(f"max records must be 10-{settings.max_records_cap}")
        if not 1 <= self.max_extract <= settings.max_extract_cap:
            raise ValueError(f"max papers to extract must be 1-{settings.max_extract_cap}")
        self.email = self.email.strip()
        if self.email and ("@" not in self.email or len(self.email) > 254):
            raise ValueError("email looks invalid")
        self.notes = self.notes.strip()[:1000]
        parse_spec(settings.screen_model)
        parse_spec(settings.extract_model)

    def context(self) -> Context:
        return Context(self.intended_use, list(self.data_types), self.coding_era, self.country,
                       self.expected_prevalence)


class Cancelled(Exception):
    pass


class Runner:
    def __init__(self, settings: Settings, store: Store, literature: Literature | None = None,
                 model_factory=build_model, mocks: dict[str, ChatModel] | None = None) -> None:
        self.settings = settings
        self.store = store
        self.lit = literature or Literature(settings, cache=store)
        self.model_factory = model_factory
        self.mocks = mocks
        self.cancelled: set[str] = set()

    def _progress(self, job_id: str, stage: str, prog: dict) -> None:
        if job_id in self.cancelled:
            raise Cancelled()
        self.store.update_job(job_id, stage=stage, progress=prog)

    def execute(self, job_id: str, spec: JobSpec) -> None:
        store, s = self.store, self.settings
        store.update_job(job_id, status="running", started_at=time.time())
        prog: dict = {"identified": {}, "log": []}
        try:
            screen_m = self.model_factory(s.screen_model, s, self.mocks)
            extract_m = self.model_factory(s.extract_model, s, self.mocks)
            studies: dict[str, Study] = {}
            oa: dict[str, bool] = {}
            seeds: set[str] = set()

            # 1. search ---------------------------------------------------------
            self._progress(job_id, "search", prog)
            errors = []
            try:
                pmids = self.lit.pubmed_search(pubmed_query(spec.condition, spec.synonyms), spec.max_records)
                prog["identified"]["pubmed"] = merge(studies, self.lit.pubmed_fetch(pmids))
            except Exception as exc:  # one source down must not sink the job
                errors.append(f"PubMed: {exc}")
            if s.use_europepmc:
                try:
                    found, oa = self.lit.europepmc_search(europepmc_query(spec.condition, spec.synonyms),
                                                          spec.max_records)
                    prog["identified"]["europepmc"] = merge(studies, found)
                except Exception as exc:
                    errors.append(f"Europe PMC: {exc}")
            titles = [t for k, ts in C.SEED_TITLES.items() if k in spec.condition.lower() for t in ts]
            if spec.model_suggestions:
                titles += suggest_titles(extract_m, spec.condition, spec.notes)
            titles = list({norm_title(t): t for t in titles}.values())
            resolved = 0
            for t in titles:
                try:
                    hit = self.lit.find_title(t)
                except Exception:
                    hit = None
                if hit:
                    merge(studies, [hit])
                    key = next((k for k, v in studies.items() if v.pmid == hit.pmid), hit.key)
                    seeds.add(key)
                    resolved += 1
            prog["identified"]["known_titles"] = {"suggested": len(titles), "resolved_in_pubmed": resolved}
            prog["log"] += errors
            if not studies:
                raise RuntimeError("literature search returned nothing" + (f" ({'; '.join(errors)})" if errors else ""))
            prog["deduplicated"] = len(studies)

            # 2. screen ---------------------------------------------------------
            self._progress(job_id, "screen", prog)
            pool = list(studies.values())
            pool.sort(key=lambda x: (x.key not in seeds))
            pool = pool[:s.max_records_cap]
            decisions = screen(screen_m, spec.condition, pool)

            # 3. snowball (one hop through the Europe PMC citation graph) ----------
            if spec.snowball:
                self._progress(job_id, "snowball", prog)
                hubs = [x for x in pool if decisions.get(x.key, {}).get("label") in ("validation", "review")]
                hubs.sort(key=lambda x: (decisions[x.key]["label"] != "review", x.key not in seeds))
                new_pmids: list[str] = []
                for st in hubs[:8]:
                    try:
                        new_pmids += [p for p in self.lit.snowball(st) if f"pmid:{p}" not in studies]
                    except Exception as exc:
                        prog["log"].append(f"citation graph: {exc}"[:300])
                new_pmids = list(dict.fromkeys(new_pmids))[:120]
                if new_pmids:
                    fresh = self.lit.pubmed_fetch(new_pmids)
                    before = set(studies)
                    prog["identified"]["snowball"] = merge(studies, fresh)
                    added = [studies[k] for k in studies if k not in before]
                    decisions.update(screen(screen_m, spec.condition, added))
                    pool += added

            included = [x for x in pool if decisions.get(x.key, {}).get("label") == "validation"]
            prog["screened"] = len(pool)
            prog["included"] = len(included)

            # 4. extract --------------------------------------------------------
            included.sort(key=lambda x: (x.key not in seeds, -(x.cited_by or 0)))
            todo = included[:spec.max_extract]
            prog["extract_total"], prog["extract_done"] = len(todo), 0
            self._progress(job_id, "extract", prog)

            def work(st: Study):
                text = ""
                if st.pmcid and oa.get(st.pmcid):
                    try:
                        text = self.lit.fulltext(st.pmcid)
                    except Exception:
                        text = ""
                st.text_basis = "full text" if text else "abstract"
                text = text or f"{st.title}\n\n{st.abstract}"
                try:
                    st.algorithms = extract(extract_m, spec.condition, st, text)
                    return None
                except (ModelError, ValueError) as exc:
                    return f"{st.key}: {exc}"

            with ThreadPoolExecutor(max_workers=max(1, s.extract_concurrency)) as tp:
                for err in tp.map(work, todo):
                    prog["extract_done"] += 1
                    if err:
                        prog["log"].append(f"extract {err}"[:300])
                    self._progress(job_id, "extract", prog)

            # 5. grade + report --------------------------------------------------
            self._progress(job_id, "grade", prog)
            extracted = [x for x in todo if x.algorithms]
            ctx = spec.context()
            cands = rank(extracted, ctx)
            result = {
                "condition": spec.condition,
                "spec": asdict(spec) | {"email": ""},
                "flow": {"identified": prog["identified"], "deduplicated": prog["deduplicated"],
                         "screened": len(pool), "included": len(included), "extracted_attempted": len(todo),
                         "extracted": len(extracted)},
                "candidates": [candidate_dict(c, i) | {"pseudocode": pseudocode(c.algorithm),
                                                       "omop_sql": omop_sql(c.algorithm)}
                               for i, c in enumerate(cands, 1)],
                "studies": [{"key": x.key, "citation": x.citation(), "url": x.url, "year": x.year,
                             "cited_by": x.cited_by, "text_basis": x.text_basis, "seed": x.key in seeds,
                             "n_algorithms": len(x.algorithms)} for x in todo],
                "excluded": [{"citation": x.citation(), "url": x.url, "label": decisions[x.key]["label"],
                              "reason": decisions[x.key]["reason"]}
                             for x in pool if decisions.get(x.key, {}).get("label") != "validation"],
                "usage": {m.spec: m.usage.as_dict() for m in {screen_m.spec: screen_m, extract_m.spec: extract_m}.values()},
                "literature_calls": self.lit.calls,
                "log": prog["log"][-50:],
            }
            job = store.get_job(job_id)
            html = render_report(job, result, self.settings)
            store.update_job(job_id, status="complete", stage="done", finished_at=time.time(),
                             result=result, report_html=html, progress=prog)
            if send_report(self.settings, spec.email, job_id, html, result):
                store.update_job(job_id, emailed_at=time.time())
        except Cancelled:
            store.update_job(job_id, status="cancelled", finished_at=time.time())
        except (ValueError, ModelError, RuntimeError) as exc:
            store.update_job(job_id, status="failed", finished_at=time.time(), error=str(exc)[:1000])
        except Exception as exc:  # the worker must never die silently
            log.error("job %s crashed: %s", job_id, traceback.format_exc())
            store.update_job(job_id, status="failed", finished_at=time.time(), error=f"internal error: {exc}"[:1000])


class JobQueue:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.pool = ThreadPoolExecutor(max_workers=max(1, runner.settings.worker_threads))

    def recover(self) -> None:
        """Jobs hold no secrets, so unfinished ones are simply re-run."""
        for job_id in self.runner.store.unfinished_jobs():
            job = self.runner.store.get_job(job_id)
            self.submit(job_id, JobSpec(**job["spec"]))

    def submit(self, job_id: str, spec: JobSpec):
        return self.pool.submit(self.runner.execute, job_id, spec)

    def cancel(self, job_id: str) -> None:
        self.runner.cancelled.add(job_id)
