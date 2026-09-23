"""Spell an algorithm out: plain-language pseudocode and an OMOP CDM SQL
template (PostgreSQL dialect; OHDSI SqlRender can translate it).

The SQL is generated deterministically from the structured algorithm, never
by a model, so what the report shows is exactly what runs.
"""
from __future__ import annotations

import re

from .schema import Algorithm, Component, Rule, norm_code

SYSTEM_LABELS = {"ICD9CM": "ICD-9-CM", "ICD10CM": "ICD-10-CM", "ICD10": "ICD-10 (WHO)",
                 "ICD10CA": "ICD-10-CA", "READ": "Read", "SNOMED": "SNOMED CT", "ICPC": "ICPC",
                 "CPT4": "CPT", "HCPCS": "HCPCS", "OPCS": "OPCS-4", "NDC": "NDC", "RxNorm": "RxNorm",
                 "ATC": "ATC", "DIN": "DIN", "LOINC": "LOINC", "text": "free text"}
OMOP_VOCAB = {"ICD9CM": "ICD9CM", "ICD10CM": "ICD10CM", "ICD10": "ICD10", "ICD10CA": "ICD10",
              "READ": "Read", "SNOMED": "SNOMED", "ICPC": "ICPC2", "CPT4": "CPT4", "HCPCS": "HCPCS",
              "OPCS": "OPCS4", "NDC": "NDC", "RxNorm": "RxNorm", "ATC": "ATC", "LOINC": "LOINC"}
ICD = ("ICD9CM", "ICD10CM", "ICD10", "ICD10CA")
# OMOP standard visit concepts: 9201 inpatient, 9202 outpatient, 9203 ER, 262 ER+inpatient.
VISITS = {"inpatient": "9201, 262", "outpatient": "9202", "emergency": "9203, 262"}
_THRESH = re.compile(r"^\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)")


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _codes_text(c: Component, limit: int = 12) -> str:
    if not c.codes:
        return "(codes not reported in the source)"
    shown = c.codes[:limit]
    more = f" (+{len(c.codes) - limit} more)" if len(c.codes) > limit else ""
    if c.domain == "drug" and c.code_system == "RxNorm":
        return ", ".join(shown) + more
    if c.code_system in ICD:
        shown = [x if x.endswith("*") else x + "*" for x in shown]
    return ", ".join(shown) + more


def describe_component(c: Component) -> str:
    what = {"diagnosis": "diagnosis", "drug": "dispensing/prescription of", "procedure": "procedure",
            "lab": "lab result", "nlp": "note mention of", "other": "record"}[c.domain]
    setting = "" if c.care_setting == "any" else f", {c.care_setting} setting"
    thr = f" {c.lab_threshold}" if c.lab_threshold else ""
    lab = f" [{c.label}]" if c.label else ""
    inferred = " (codes inferred, not from the paper)" if c.codes and c.codes_source == "inferred" else ""
    return f"{what} {SYSTEM_LABELS.get(c.code_system, c.code_system)} {_codes_text(c)}{thr}{setting}{lab}{inferred}"


def describe_rule(r: Rule) -> list[str]:
    days = "distinct days" if r.min_events > 1 else "day"
    win = f" within any {r.window_days}-day window" if r.window_days else " (any time)"
    head = f">= {r.min_events} qualifying event{'s' if r.min_events > 1 else ''} on {days}{win}"
    if r.min_separation_days:
        head += f", first and last at least {r.min_separation_days} days apart"
    if r.require_each and len(r.components) > 1:
        head += ", with every event type below present"
    return [head + ", where an event is:"] + [f"  - {describe_component(c)}" for c in r.components]


def pseudocode(a: Algorithm) -> str:
    lines = ["CASE if ANY of the following rules is met:" if len(a.rules) > 1 else "CASE if:"]
    for i, r in enumerate(a.rules, 1):
        lines.append(f"  Rule {i}{' - ' + r.label if r.label else ''}:")
        lines += ["    " + x for x in describe_rule(r)]
    if a.age_min is not None:
        lines.append(f"AND age >= {a.age_min} at index date")
    if a.lookback_days:
        lines.append(f"AND >= {a.lookback_days} days of continuous observation before the index date")
    if a.exclusions:
        lines.append("EXCLUDE if any:")
        lines += [f"  - {describe_component(c)}" for c in a.exclusions]
    lines.append("Index date: first event of the earliest qualifying window.")
    return "\n".join(lines)


def _visit_join(alias: str, c: Component) -> str:
    if c.care_setting == "any":
        return ""
    return (f"\n  JOIN @cdm.visit_occurrence vo ON vo.visit_occurrence_id = {alias}.visit_occurrence_id"
            f" AND vo.visit_concept_id IN ({VISITS[c.care_setting]})")


def component_sql(c: Component) -> str:
    """SELECT person_id, event_date for one component."""
    vocab = OMOP_VOCAB.get(c.code_system)
    if not c.codes:
        return ("SELECT NULL::bigint AS person_id, NULL::date AS event_date WHERE FALSE"
                f"  -- TODO: codes not reported in the source for: {c.label}")
    if c.domain == "nlp" or c.code_system == "text":
        terms = ", ".join(_q(t.lower()) for t in c.codes) or "''"
        return ("SELECT n.person_id, nn.note_nlp_date AS event_date\n  FROM @cdm.note_nlp nn\n"
                "  JOIN @cdm.note n ON n.note_id = nn.note_id\n"
                f"  WHERE LOWER(nn.lexical_variant) IN ({terms})\n"
                "    AND COALESCE(nn.term_exists, 'Y') = 'Y'  -- drop negated mentions")
    if vocab is None:
        return f"SELECT NULL::bigint AS person_id, NULL::date AS event_date WHERE FALSE  -- {c.code_system} has no OMOP vocabulary; map manually"
    if c.domain == "drug":
        if c.code_system in ("RxNorm", "ATC"):
            match = (f"LOWER(c.concept_name) IN ({', '.join(_q(x.lower()) for x in c.codes)})"
                     " AND c.concept_class_id = 'Ingredient'" if c.code_system == "RxNorm"
                     else "(" + " OR ".join(f"c.concept_code LIKE {_q(x.rstrip('*') + '%')}" for x in c.codes) + ")")
            return ("SELECT de.person_id, de.drug_exposure_start_date AS event_date\n  FROM @cdm.drug_exposure de\n"
                    "  JOIN @cdm.concept_ancestor ca ON ca.descendant_concept_id = de.drug_concept_id\n"
                    f"  JOIN @cdm.concept c ON c.concept_id = ca.ancestor_concept_id{_visit_join('de', c)}\n"
                    f"  WHERE c.vocabulary_id = {_q(vocab)} AND {match}")
        return ("SELECT de.person_id, de.drug_exposure_start_date AS event_date\n  FROM @cdm.drug_exposure de\n"
                f"  JOIN @cdm.concept c ON c.concept_id = de.drug_source_concept_id{_visit_join('de', c)}\n"
                f"  WHERE c.vocabulary_id = {_q(vocab)} AND c.concept_code IN ({', '.join(_q(x) for x in c.codes)})")
    if c.domain == "lab":
        extra = ""
        m = _THRESH.match(c.lab_threshold or "")
        if m:
            extra = f"\n    AND m.value_as_number {m.group(1)} {m.group(2)}"
        elif c.lab_threshold:
            extra = f"\n    -- threshold to apply by hand: {c.lab_threshold}"
        return ("SELECT m.person_id, m.measurement_date AS event_date\n  FROM @cdm.measurement m\n"
                f"  JOIN @cdm.concept c ON c.concept_id = m.measurement_concept_id{_visit_join('m', c)}\n"
                f"  WHERE c.vocabulary_id = {_q(vocab)} AND c.concept_code IN ({', '.join(_q(x) for x in c.codes)}){extra}")
    if c.domain == "procedure":
        return ("SELECT po.person_id, po.procedure_date AS event_date\n  FROM @cdm.procedure_occurrence po\n"
                f"  JOIN @cdm.concept c ON c.concept_id = po.procedure_source_concept_id{_visit_join('po', c)}\n"
                f"  WHERE c.vocabulary_id = {_q(vocab)} AND c.concept_code IN ({', '.join(_q(x) for x in c.codes)})")
    # diagnosis / other -> condition_occurrence
    if c.code_system == "SNOMED":
        return ("SELECT co.person_id, co.condition_start_date AS event_date\n  FROM @cdm.condition_occurrence co\n"
                "  JOIN @cdm.concept_ancestor ca ON ca.descendant_concept_id = co.condition_concept_id\n"
                f"  JOIN @cdm.concept c ON c.concept_id = ca.ancestor_concept_id{_visit_join('co', c)}\n"
                f"  WHERE c.vocabulary_id = 'SNOMED' AND c.concept_code IN ({', '.join(_q(x) for x in c.codes)})")
    if c.code_system in ICD:
        match = " OR ".join(f"REPLACE(c.concept_code, '.', '') LIKE {_q(norm_code(x, c.code_system) + '%')}"
                            for x in c.codes)
    else:
        match = f"c.concept_code IN ({', '.join(_q(x) for x in c.codes)})"
    return ("SELECT co.person_id, co.condition_start_date AS event_date\n  FROM @cdm.condition_occurrence co\n"
            f"  JOIN @cdm.concept c ON c.concept_id = co.condition_source_concept_id{_visit_join('co', c)}\n"
            f"  WHERE c.vocabulary_id = {_q(vocab)} AND ({match})")


def omop_sql(a: Algorithm) -> str:
    ctes: list[str] = []
    hit_names = []
    for i, r in enumerate(a.rules, 1):
        parts = []
        for j, c in enumerate(r.components, 1):
            name = f"r{i}_c{j}"
            ctes.append(f"{name} AS (  -- {describe_component(c)[:110]}\n  {component_sql(c)}\n)")
            parts.append(f"SELECT person_id, event_date, {j} AS comp FROM {name}")
        ctes.append(f"r{i}_events AS (\n  " + "\n  UNION ALL ".join(parts) + "\n)")
        upper = f"\n   AND b.event_date < a.event_date + {r.window_days}" if r.window_days else ""
        having = [f"COUNT(DISTINCT b.event_date) >= {r.min_events}"]
        if r.min_separation_days:
            having.append(f"MAX(b.event_date) - a.event_date >= {r.min_separation_days}")
        if r.require_each and len(r.components) > 1:
            having.append(f"COUNT(DISTINCT b.comp) = {len(r.components)}")
        ctes.append(
            f"r{i}_hits AS (  -- rule {i}{': ' + r.label[:80] if r.label else ''}\n"
            f"  SELECT a.person_id, a.event_date AS index_date\n"
            f"  FROM (SELECT DISTINCT person_id, event_date FROM r{i}_events) a\n"
            f"  JOIN r{i}_events b ON b.person_id = a.person_id\n"
            f"   AND b.event_date >= a.event_date{upper}\n"
            f"  GROUP BY a.person_id, a.event_date\n"
            f"  HAVING " + "\n     AND ".join(having) + "\n)")
        hit_names.append(f"r{i}_hits")
    for k, c in enumerate(a.exclusions, 1):
        ctes.append(f"excl_{k} AS (  -- exclusion: {describe_component(c)[:100]}\n  {component_sql(c)}\n)")
    ctes.append("cases AS (\n  SELECT person_id, MIN(index_date) AS index_date FROM (\n    "
                + "\n    UNION ALL ".join(f"SELECT person_id, index_date FROM {h}" for h in hit_names)
                + "\n  ) h GROUP BY person_id\n)")
    where = []
    if a.age_min is not None:
        where.append(f"EXTRACT(YEAR FROM c.index_date) - p.year_of_birth >= {a.age_min}")
    if a.lookback_days:
        where.append("EXISTS (SELECT 1 FROM @cdm.observation_period op WHERE op.person_id = c.person_id\n"
                     f"         AND op.observation_period_start_date <= c.index_date - {a.lookback_days}\n"
                     "         AND op.observation_period_end_date >= c.index_date)")
    for k in range(1, len(a.exclusions) + 1):
        where.append(f"NOT EXISTS (SELECT 1 FROM excl_{k} e WHERE e.person_id = c.person_id)")
    header = (f"-- sauce.ai/phenotype: {a.name}\n"
              "-- OMOP CDM v5.4, PostgreSQL dialect. Replace @cdm with your CDM schema.\n"
              "-- Generated from the structured algorithm; review code lists against the source paper.\n")
    body = ("WITH\n" + ",\n".join(ctes) + "\nSELECT c.person_id, c.index_date\nFROM cases c\n"
            "JOIN @cdm.person p ON p.person_id = c.person_id")
    if where:
        body += "\nWHERE " + "\n  AND ".join(where)
    return header + body + ";\n"
