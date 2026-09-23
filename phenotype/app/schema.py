"""Structured phenotype algorithms and their validation results.

Model output is untrusted: every ``from_dict`` coerces types, clamps to the
controlled vocabularies in ``catalog`` and drops what it cannot use, so the
grader and the SQL compiler only ever see well-formed objects.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .catalog import (CARE_SETTINGS, CODE_SYSTEMS, CODING_ERAS, DATA_TYPES, DOMAINS, METRICS,
                      REFERENCE_STANDARDS, SAMPLING)

_CODE_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .\-*/+(),']{0,79}$")


def _s(v, n: int = 400) -> str:
    return re.sub(r"\s+", " ", str(v)).strip()[:n] if v is not None else ""


def _int(v, lo: int, hi: int, default: int | None) -> int | None:
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def _prop(v) -> float | None:
    """Proportion in [0, 1]; accepts percentages (e.g. 94.2 -> 0.942)."""
    try:
        f = float(str(v).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    if 1 < f <= 100:
        f /= 100
    return round(f, 6) if 0 <= f <= 1 else None


def _pick(v, allowed, default: str) -> str:
    v = _s(v, 40)
    for a in allowed:
        if v.lower() == a.lower():
            return a
    return default


def norm_code(code: str, system: str) -> str:
    c = code.strip().upper().rstrip("*").rstrip("X").replace(" ", "")
    if system in ("ICD9CM", "ICD10CM", "ICD10", "ICD10CA"):
        c = c.replace(".", "")
    return c


@dataclass
class Component:
    domain: str = "diagnosis"
    code_system: str = "ICD10CM"
    codes: list[str] = field(default_factory=list)
    care_setting: str = "any"
    label: str = ""
    lab_threshold: str = ""
    codes_source: str = "paper"   # paper | inferred (standard codes filled in by the model)

    @classmethod
    def from_dict(cls, d: dict) -> "Component | None":
        if not isinstance(d, dict):
            return None
        domain = _pick(d.get("domain"), DOMAINS, "other")
        system = _pick(d.get("code_system"), CODE_SYSTEMS, "text")
        codes = []
        for c in d.get("codes") or []:
            c = _s(c, 80)
            if c and _CODE_OK.match(c) and c not in codes:
                codes.append(c)
        label = _s(d.get("label"), 160)
        if not codes and not label:
            return None
        return cls(domain=domain, code_system=system, codes=codes[:300],
                   care_setting=_pick(d.get("care_setting"), CARE_SETTINGS, "any"),
                   label=label, lab_threshold=_s(d.get("lab_threshold"), 120),
                   codes_source=_pick(d.get("codes_source"), ("paper", "inferred"), "paper"))

    def normalized_codes(self) -> list[str]:
        if self.domain == "drug":
            return sorted({c.strip().lower() for c in self.codes})
        return sorted({norm_code(c, self.code_system) for c in self.codes})


@dataclass
class Rule:
    """Pooled event count: >= min_events qualifying events (from any component)
    within window_days, events >= min_separation_days apart; with
    require_each, every component must contribute at least one event."""
    components: list[Component] = field(default_factory=list)
    min_events: int = 1
    window_days: int | None = None
    min_separation_days: int = 0
    require_each: bool = False
    label: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Rule | None":
        if not isinstance(d, dict):
            return None
        comps = [c for c in (Component.from_dict(x) for x in d.get("components") or []) if c]
        if not comps:
            return None
        return cls(components=comps, min_events=_int(d.get("min_events"), 1, 50, 1),
                   window_days=_int(d.get("window_days"), 1, 36500, None),
                   min_separation_days=_int(d.get("min_separation_days"), 0, 3650, 0) or 0,
                   require_each=bool(d.get("require_each")), label=_s(d.get("label"), 200))


@dataclass
class Algorithm:
    name: str
    summary: str = ""
    rules: list[Rule] = field(default_factory=list)       # OR-ed
    exclusions: list[Component] = field(default_factory=list)
    age_min: int | None = None
    lookback_days: int | None = None
    data_types: list[str] = field(default_factory=list)
    coding_era: str = "both"
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Algorithm | None":
        if not isinstance(d, dict):
            return None
        rules = [r for r in (Rule.from_dict(x) for x in d.get("rules") or []) if r]
        if not rules:
            return None
        excl = [c for c in (Component.from_dict(x) for x in d.get("exclusions") or []) if c]
        dts = [t for t in (d.get("data_types") or []) if t in DATA_TYPES]
        return cls(name=_s(d.get("name"), 200) or "Unnamed algorithm", summary=_s(d.get("summary"), 1500),
                   rules=rules[:10], exclusions=excl[:20], age_min=_int(d.get("age_min"), 0, 120, None),
                   lookback_days=_int(d.get("lookback_days"), 1, 36500, None), data_types=dts,
                   coding_era=_pick(d.get("coding_era"), CODING_ERAS, "both"), notes=_s(d.get("notes"), 1500))

    def signature(self) -> tuple:
        """Identity for clustering the same algorithm across studies: code
        categories (ICD to 3 characters) + count logic, ignoring labels."""
        def comp_sig(c: Component):
            codes = c.normalized_codes()
            if c.code_system in ("ICD9CM", "ICD10CM", "ICD10", "ICD10CA"):
                codes = sorted({x[:3] for x in codes})
            return (c.domain, "ICD" if c.code_system.startswith("ICD") else c.code_system,
                    tuple(codes), c.care_setting)
        rules = []
        for r in self.rules:
            comps = tuple(sorted(comp_sig(c) for c in r.components if c.domain != "drug"))
            has_drug = any(c.domain == "drug" for c in r.components)
            rules.append((comps, has_drug, r.min_events, r.window_days or 0, r.min_separation_days,
                          r.require_each))
        return tuple(sorted(rules))

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class MetricValue:
    value: float | None = None
    lo: float | None = None
    hi: float | None = None
    x: int | None = None
    n: int | None = None
    quote: str = ""
    verified: bool = False

    @classmethod
    def from_dict(cls, d) -> "MetricValue | None":
        if not isinstance(d, dict):
            v = _prop(d)
            return cls(value=v) if v is not None else None
        m = cls(value=_prop(d.get("value")), lo=_prop(d.get("lo")), hi=_prop(d.get("hi")),
                x=_int(d.get("x"), 0, 10**8, None), n=_int(d.get("n"), 1, 10**8, None),
                quote=_s(d.get("quote"), 600))
        if m.x is not None and (m.n is None or m.x > m.n):
            m.x = None
        if m.value is None and m.x is not None and m.n:
            m.value = m.x / m.n
        if m.value is None:
            return None
        if m.lo is not None and m.hi is not None and not (m.lo <= m.value <= m.hi):
            m.lo = m.hi = None
        return m


@dataclass
class Validation:
    dataset: str = ""
    country: str = ""
    data_type: str = ""
    years: str = ""
    population: str = ""
    n_validated: int | None = None
    reference_standard: str = "unclear"
    reference_detail: str = ""
    sampling: str = "unclear"
    blinded: bool | None = None
    external: bool = False
    metrics: dict[str, MetricValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Validation | None":
        if not isinstance(d, dict):
            return None
        sampling = _pick(d.get("sampling"), SAMPLING, "unclear")
        metrics = {}
        for k in METRICS:
            m = MetricValue.from_dict((d.get("metrics") or {}).get(k))
            if m and k in SAMPLING[sampling]["estimable"]:
                metrics[k] = m
        if not metrics:
            return None
        b = d.get("blinded")
        return cls(dataset=_s(d.get("dataset"), 200), country=_s(d.get("country"), 80),
                   data_type=_pick(d.get("data_type"), DATA_TYPES, ""), years=_s(d.get("years"), 40),
                   population=_s(d.get("population"), 300), n_validated=_int(d.get("n_validated"), 1, 10**8, None),
                   reference_standard=_pick(d.get("reference_standard"), REFERENCE_STANDARDS, "unclear"),
                   reference_detail=_s(d.get("reference_detail"), 400), sampling=sampling,
                   blinded=b if isinstance(b, bool) else None, external=bool(d.get("external")),
                   metrics=metrics)


@dataclass
class ExtractedAlgorithm:
    algorithm: Algorithm
    validations: list[Validation]
    role: str = "developed"   # developed | validated_existing | applied_only

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractedAlgorithm | None":
        if not isinstance(d, dict):
            return None
        alg = Algorithm.from_dict(d.get("algorithm"))
        vals = [v for v in (Validation.from_dict(x) for x in d.get("validations") or []) if v]
        if not alg or not vals:
            return None
        return cls(alg, vals[:12], _pick(d.get("role"), ("developed", "validated_existing", "applied_only"),
                                         "developed"))


@dataclass
class Study:
    key: str
    title: str
    authors: str = ""
    journal: str = ""
    year: int | None = None
    pmid: str = ""
    pmcid: str = ""
    doi: str = ""
    abstract: str = ""
    cited_by: int | None = None
    text_basis: str = "abstract"
    algorithms: list[ExtractedAlgorithm] = field(default_factory=list)

    @property
    def url(self) -> str:
        if self.pmid:
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return ""

    def citation(self) -> str:
        first = self.authors.split(",")[0].strip() if self.authors else ""
        etal = " et al" if "," in self.authors else ""
        bits = [f"{first}{etal}" if first else "", self.title.rstrip("."), self.journal,
                str(self.year or "")]
        return ". ".join(b.rstrip(".") for b in bits if b) + "."
