"""Controlled vocabularies, scoring weights and the worked exemplar.

Everything the grader and the report rely on is declared here so the
ranking method is auditable in one place (and printed in the report's
Methods section).
"""
from __future__ import annotations

METRICS = ("sensitivity", "specificity", "ppv", "npv")
METRIC_LABELS = {"sensitivity": "Sensitivity", "specificity": "Specificity",
                 "ppv": "PPV", "npv": "NPV"}

# Intended use decides which accuracy metrics matter. Weights sum to 1.
INTENDED_USES = {
    "prevalence": {
        "label": "Prevalence / incidence estimation",
        "help": "Counting cases in a population. False positives and false negatives both bias the "
                "estimate; at low prevalence specificity dominates.",
        "weights": {"sensitivity": 0.35, "specificity": 0.40, "ppv": 0.25, "npv": 0.0},
        "primary": ("sensitivity", "specificity"),
    },
    "cohort": {
        "label": "Cohort / case definition for an etiologic or outcomes study",
        "help": "Case purity matters most: misclassified non-cases dilute associations.",
        "weights": {"sensitivity": 0.15, "specificity": 0.20, "ppv": 0.65, "npv": 0.0},
        "primary": ("ppv",),
    },
    "case_finding": {
        "label": "Case-finding for chart review, surveillance, or trial recruitment",
        "help": "Missing true cases is the costly error; chart review removes false positives.",
        "weights": {"sensitivity": 0.60, "specificity": 0.05, "ppv": 0.15, "npv": 0.20},
        "primary": ("sensitivity",),
    },
}

DATA_TYPES = {
    "claims": "Administrative claims (billing codes, pharmacy dispensing)",
    "ehr_structured": "EHR structured data (diagnoses, orders, labs, medications)",
    "ehr_notes": "EHR with clinical notes (NLP available)",
    "registry": "Disease or population registry linkage",
}

CODING_ERAS = {
    "icd10": "ICD-10 era (US data after Oct 2015; most non-US data)",
    "icd9": "ICD-9 era only",
    "both": "Spans both eras",
}

DOMAINS = ("diagnosis", "drug", "procedure", "lab", "nlp", "other")
CODE_SYSTEMS = ("ICD9CM", "ICD10CM", "ICD10", "ICD10CA", "READ", "SNOMED", "ICPC",
                "CPT4", "HCPCS", "OPCS", "NDC", "RxNorm", "ATC", "DIN", "LOINC", "text")
CARE_SETTINGS = ("any", "inpatient", "outpatient", "emergency")

# Reference standard: how the "truth" in the validation study was established.
# risk = QUADAS-2 style risk-of-bias judgement for the reference-standard domain.
REFERENCE_STANDARDS = {
    "chart_review_criteria": {"label": "Chart review against explicit diagnostic criteria", "risk": "low"},
    "chart_review": {"label": "Chart review (criteria not stated)", "risk": "unclear"},
    "registry": {"label": "Registry / adjudicated cohort", "risk": "unclear"},
    "clinical_exam": {"label": "Clinical examination / prospective diagnosis", "risk": "low"},
    "self_report": {"label": "Patient self-report / survey", "risk": "high"},
    "other_algorithm": {"label": "Another algorithm or data source", "risk": "high"},
    "unclear": {"label": "Not reported", "risk": "unclear"},
}

# Sampling: who was verified. Decides which metrics are estimable at all.
SAMPLING = {
    "population_random": {"label": "Random / consecutive sample of the source population",
                          "risk": "low", "estimable": set(METRICS)},
    "stratified": {"label": "Stratified by algorithm status (weighted back)",
                   "risk": "unclear", "estimable": set(METRICS)},
    "positives_only": {"label": "Algorithm-positives only",
                       "risk": "low", "estimable": {"ppv"}},
    "case_control": {"label": "Known cases vs. known non-cases",
                     "risk": "high", "estimable": {"sensitivity", "specificity"}},
    "unclear": {"label": "Not reported", "risk": "unclear", "estimable": set(METRICS)},
}

RISK_SCORE = {"low": 1.0, "unclear": 0.5, "high": 0.0}

# Evidence grade (GRADE-style: start high, downgrade per concern).
GRADES = {4: ("High", "A"), 3: ("Moderate", "B"), 2: ("Low", "C"), 1: ("Very low", "D")}

# Composite score knobs (documented in the report).
MISSING_METRIC_VALUE = 0.5     # an unestimated metric counts as a coin flip
IMPRECISE_CI_WIDTH = 0.20      # 95% CI wider than this -> downgrade for imprecision
INCONSISTENT_I2 = 0.50
MIN_TOTAL_N = 100
ASSUMED_N_CAP = 100      # denominator assumed when only p and records verified are reported

# Worked example given to the extraction model: the case definition validated
# by the MS Prevalence Working Group and used for the 2019 US MS prevalence
# estimate. Structure only; accuracy numbers always come from the papers.
EXEMPLAR = {
    "condition": "multiple sclerosis",
    "citation": ("Culpepper WJ, Marrie RA, Langer-Gould A, et al. Validation of an algorithm for "
                 "identifying MS cases in administrative health claims datasets. Neurology. "
                 "2019;92(10):e1016-e1028."),
    "applied_in": ("Wallin MT, Culpepper WJ, Campbell JD, et al. The prevalence of MS in the United "
                   "States: a population-based estimate using health claims data. Neurology. "
                   "2019;92(10):e1029-e1040."),
    "algorithm": {
        "name": ">=3 MS-related claims within 1 year",
        "summary": ("A person is a case if they have 3 or more MS-related claims (an inpatient or "
                    "outpatient claim with an MS diagnosis code, or a dispensing of an MS "
                    "disease-modifying therapy) within any 1-year period."),
        "rules": [{
            "label": "Any 3 MS-related claims in 365 days",
            "min_events": 3, "window_days": 365, "min_separation_days": 0, "require_each": False,
            "components": [
                {"domain": "diagnosis", "code_system": "ICD9CM", "codes": ["340"], "care_setting": "any",
                 "label": "MS diagnosis (ICD-9-CM)"},
                {"domain": "diagnosis", "code_system": "ICD10CM", "codes": ["G35"], "care_setting": "any",
                 "label": "MS diagnosis (ICD-10-CM)"},
                {"domain": "drug", "code_system": "RxNorm",
                 "codes": ["interferon beta-1a", "interferon beta-1b", "peginterferon beta-1a",
                           "glatiramer acetate", "natalizumab", "fingolimod", "teriflunomide",
                           "dimethyl fumarate", "alemtuzumab", "ocrelizumab"],
                 "care_setting": "any", "label": "MS disease-modifying therapy"},
            ],
        }],
        "exclusions": [],
        "age_min": 18,
        "lookback_days": None,
        "data_types": ["claims"],
        "coding_era": "both",
        "notes": "Validated in multiple independent datasets with chart review as the reference standard.",
    },
}

# Titles we always try to resolve for a condition, in addition to search and
# model suggestions. Keys are lowercase substrings of the condition.
SEED_TITLES = {
    "multiple sclerosis": [
        "Validation of an algorithm for identifying MS cases in administrative health claims datasets",
    ],
}
