"""Cluster, pool, grade and rank candidate algorithms.

Pipeline for one condition:

1. Cluster extracted algorithms across studies by ``Algorithm.signature``.
2. Pool each accuracy metric over the cluster's validations (logit-scale
   DerSimonian-Laird, ``metrics.pool``).
3. Judge risk of bias per validation (QUADAS-2-style: reference standard,
   patient sampling, blinding) and applicability to the user's setting.
4. Grade certainty GRADE-style (start High, downgrade per concern).
5. Composite score = accuracy x quality x applicability x replication;
   rank by it, grade breaks ties.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import catalog as C
from .metrics import apparent_prevalence, npv_at, pool, ppv_at, rogan_gladen, to_logit_estimate
from .schema import Algorithm, Study, Validation


@dataclass
class Context:
    """The user's setting, for applicability and use-weighted accuracy."""
    intended_use: str = "prevalence"
    data_types: list[str] = field(default_factory=lambda: ["claims"])
    coding_era: str = "icd10"
    country: str = ""
    expected_prevalence: float | None = None


def validation_risk(v: Validation) -> dict:
    ref = C.REFERENCE_STANDARDS[v.reference_standard]["risk"]
    samp = C.SAMPLING[v.sampling]["risk"]
    blind = {True: "low", False: "high", None: "unclear"}[v.blinded]
    domains = {"reference_standard": ref, "patient_selection": samp, "blinding": blind}
    vals = list(domains.values())
    overall = "high" if "high" in vals else ("low" if all(x == "low" for x in vals) else "unclear")
    return {"domains": domains, "overall": overall,
            "score": sum(C.RISK_SCORE[x] for x in vals) / len(vals)}


def applicability(alg: Algorithm, vals: list[Validation], ctx: Context) -> tuple[float, list[str]]:
    """Multiplicative factor in [0.5, 1] with the reasons it is below 1."""
    f, why = 1.0, []
    vtypes = {v.data_type for v in vals if v.data_type} | set(alg.data_types)
    if vtypes and ctx.data_types and not (vtypes & set(ctx.data_types)):
        # An algorithm built on claims is usually runnable on EHR structured data
        # (codes exist in both), less so the other way round.
        near = "claims" in vtypes and "ehr_structured" in ctx.data_types
        f *= 0.9 if near else 0.75
        why.append(f"validated on {', '.join(sorted(vtypes))}, your data is {', '.join(ctx.data_types)}")
    systems = {c.code_system for r in alg.rules for c in r.components}
    if ctx.coding_era == "icd10" and "ICD9CM" in systems and not systems & {"ICD10CM", "ICD10", "ICD10CA"}:
        f *= 0.7
        why.append("ICD-9 codes only; needs an ICD-10 translation (GEMs) that was not validated")
    if ctx.coding_era == "icd9" and systems & {"ICD10CM"} and "ICD9CM" not in systems:
        f *= 0.8
        why.append("ICD-10-CM codes only; your data is ICD-9 era")
    if "nlp" in {c.domain for r in alg.rules for c in r.components} and "ehr_notes" not in ctx.data_types:
        f *= 0.6
        why.append("requires clinical-note NLP, which your data does not include")
    if ctx.country:
        countries = {v.country.lower() for v in vals if v.country}
        if countries and ctx.country.lower() not in countries:
            f *= 0.9
            why.append(f"validated in {', '.join(sorted(countries))}, not {ctx.country}")
    return max(0.5, f), why


@dataclass
class Candidate:
    algorithm: Algorithm
    members: list[tuple[Study, Validation]]
    pooled: dict = field(default_factory=dict)
    risk: list[dict] = field(default_factory=list)
    applicability: float = 1.0
    applicability_notes: list[str] = field(default_factory=list)
    accuracy: float = 0.0
    quality: float = 0.0
    replication: float = 0.0
    composite: float = 0.0
    grade: dict = field(default_factory=dict)
    at_prevalence: dict | None = None

    @property
    def studies(self) -> list[Study]:
        seen, out = set(), []
        for s, _ in self.members:
            if s.key not in seen:
                seen.add(s.key)
                out.append(s)
        return out


def cluster(studies: list[Study]) -> list[Candidate]:
    groups: dict[tuple, Candidate] = {}
    for s in studies:
        for ea in s.algorithms:
            sig = ea.algorithm.signature()
            cand = groups.get(sig)
            if cand is None:
                cand = groups[sig] = Candidate(ea.algorithm, [])
            elif ea.role == "developed" and len(ea.algorithm.summary) > len(cand.algorithm.summary):
                cand.algorithm = ea.algorithm   # keep the fullest original description
            cand.members += [(s, v) for v in ea.validations]
    return list(groups.values())


def _denominator(v: Validation, metric: str, m) -> tuple[float | None, bool]:
    """(denominator, assumed). When only a point estimate and the number of
    verified records are reported, the metric's own denominator (cases for
    sensitivity, non-cases for specificity, ...) is unknown: assume half the
    verified records, capped at ASSUMED_N_CAP, so precision is not overstated."""
    if m.n:
        return m.n, False
    if not v.n_validated:
        return None, False
    if metric == "ppv" and v.sampling == "positives_only":
        return v.n_validated, False
    return max(10.0, min(v.n_validated / 2, C.ASSUMED_N_CAP)), True


def _pool_metric(members, metric: str, verified_only: bool) -> dict | None:
    ests, assumed = [], False
    for _, v in members:
        m = v.metrics.get(metric)
        if not m or (verified_only and not m.verified):
            continue
        n, guess = _denominator(v, metric, m)
        e = to_logit_estimate(m.value, m.lo, m.hi, m.x, n)
        if e:
            ests.append(e)
            assumed |= guess and e.source == "n"
    out = pool(ests)
    if out:
        out["verified"] = verified_only
        out["assumed_n"] = assumed
    return out


def grade(cand: Candidate, ctx: Context) -> dict:
    level, reasons = 4, []
    use = C.INTENDED_USES[ctx.intended_use]
    primary = [cand.pooled.get(m) for m in use["primary"]]
    if not all(primary):
        level -= 1
        missing = [C.METRIC_LABELS[m] for m, p in zip(use["primary"], primary) if not p]
        reasons.append(f"indirectness: {', '.join(missing)} not estimated for this use")
    overall = [r["overall"] for r in cand.risk]
    if overall.count("high") * 2 >= len(overall):
        level -= 2
        reasons.append("risk of bias: serious (most validations high risk)")
    elif overall.count("low") * 2 < len(overall):
        level -= 1
        reasons.append("risk of bias: most validations unclear or high risk")
    present = [p for p in primary if p]
    if any(p["k"] > 1 and p["i2"] > C.INCONSISTENT_I2 for p in present):
        level -= 1
        reasons.append("inconsistency: I^2 > 50% across validations")
    if any(p["hi"] - p["lo"] > C.IMPRECISE_CI_WIDTH for p in present) or \
            sum(v.n_validated or 0 for _, v in cand.members) < C.MIN_TOTAL_N:
        level -= 1
        reasons.append("imprecision: wide 95% CI or fewer than 100 records verified")
    if cand.applicability < 0.8:
        level -= 1
        reasons.append("indirectness: " + "; ".join(cand.applicability_notes))
    if len(cand.members) == 1 and not cand.members[0][1].external:
        level -= 1
        reasons.append("single validation, no external or independent replication")
    if any(not p.get("verified") for m, p in cand.pooled.items() if use["weights"].get(m)):
        level -= 1
        reasons.append("extraction: a supporting quote was not found verbatim in the source")
    level = max(1, min(4, level))
    label, letter = C.GRADES[level]
    return {"level": level, "label": label, "letter": letter, "reasons": reasons}


def score(cand: Candidate, ctx: Context) -> Candidate:
    use = C.INTENDED_USES[ctx.intended_use]
    for m in C.METRICS:
        p = _pool_metric(cand.members, m, verified_only=True) or _pool_metric(cand.members, m, verified_only=False)
        if p:
            cand.pooled[m] = p
    cand.risk = [validation_risk(v) for _, v in cand.members]
    cand.applicability, cand.applicability_notes = applicability(
        cand.algorithm, [v for _, v in cand.members], ctx)
    # Accuracy: use-weighted lower 95% confidence limits (conservative).
    cand.accuracy = sum(w * (cand.pooled[m]["lo"] if m in cand.pooled else C.MISSING_METRIC_VALUE)
                        for m, w in use["weights"].items())
    cand.quality = 0.6 + 0.4 * sum(r["score"] for r in cand.risk) / max(1, len(cand.risk))
    k_sets = len({(s.key, v.dataset) for s, v in cand.members})
    cand.replication = min(1.0, 0.85 + 0.05 * k_sets)
    cand.composite = cand.accuracy * cand.quality * cand.applicability * cand.replication
    cand.grade = grade(cand, ctx)
    se, sp = cand.pooled.get("sensitivity"), cand.pooled.get("specificity")
    if ctx.expected_prevalence and se and sp:
        p = ctx.expected_prevalence
        app = apparent_prevalence(se["value"], sp["value"], p)
        cand.at_prevalence = {"prevalence": p, "ppv": ppv_at(se["value"], sp["value"], p),
                              "npv": npv_at(se["value"], sp["value"], p), "apparent_prevalence": app,
                              "rogan_gladen_check": rogan_gladen(app, se["value"], sp["value"])}
    return cand


def rank(studies: list[Study], ctx: Context) -> list[Candidate]:
    cands = [score(c, ctx) for c in cluster(studies)]
    cands.sort(key=lambda c: (-c.composite, -c.grade["level"], -len(c.members)))
    return cands


def candidate_dict(c: Candidate, rank_no: int) -> dict:
    return {
        "rank": rank_no,
        "algorithm": c.algorithm.as_dict(),
        "composite": round(c.composite, 4),
        "components": {"accuracy": round(c.accuracy, 4), "quality": round(c.quality, 4),
                       "applicability": round(c.applicability, 4), "replication": round(c.replication, 4)},
        "grade": c.grade,
        "pooled": c.pooled,
        "applicability_notes": c.applicability_notes,
        "at_prevalence": c.at_prevalence,
        "validations": [
            {"study": s.key, "citation": s.citation(), "url": s.url, "pmid": s.pmid, "doi": s.doi,
             "dataset": v.dataset, "country": v.country, "data_type": v.data_type, "years": v.years,
             "population": v.population, "n_validated": v.n_validated,
             "reference_standard": v.reference_standard, "reference_detail": v.reference_detail,
             "sampling": v.sampling, "blinded": v.blinded, "external": v.external,
             "risk": r, "metrics": {k: m.__dict__ for k, m in v.metrics.items()}}
            for (s, v), r in zip(c.members, c.risk)],
    }
