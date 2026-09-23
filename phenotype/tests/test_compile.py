from app.catalog import EXEMPLAR
from app.compile import omop_sql, pseudocode
from app.schema import Algorithm


def ms():
    return Algorithm.from_dict(EXEMPLAR["algorithm"])


def test_pseudocode_spells_out_exemplar():
    text = pseudocode(ms())
    assert ">= 3 qualifying events on distinct days within any 365-day window" in text
    assert "ICD-10-CM G35*" in text and "ICD-9-CM 340*" in text
    assert "glatiramer acetate" in text
    assert "age >= 18" in text


def test_sql_structure():
    sql = omop_sql(ms())
    assert "REPLACE(c.concept_code, '.', '') LIKE 'G35%'" in sql
    assert "c.vocabulary_id = 'ICD9CM'" in sql
    assert "concept_ancestor" in sql and "'natalizumab'" in sql
    assert "COUNT(DISTINCT b.event_date) >= 3" in sql
    assert "b.event_date < a.event_date + 365" in sql
    assert "year_of_birth >= 18" in sql
    assert sql.rstrip().endswith(";")


def test_sql_or_rules_settings_separation_exclusions_and_escaping():
    alg = Algorithm.from_dict({
        "name": "1 inpatient or 2 outpatient", "age_min": None, "lookback_days": 365,
        "rules": [
            {"min_events": 1, "components": [{"domain": "diagnosis", "code_system": "ICD10CM",
                                              "codes": ["E11.*"], "care_setting": "inpatient", "label": "T2D"}]},
            {"min_events": 2, "window_days": 730, "min_separation_days": 30,
             "components": [{"domain": "diagnosis", "code_system": "ICD10CM", "codes": ["E11"],
                             "care_setting": "outpatient", "label": "T2D"}]},
            {"min_events": 2, "require_each": True,
             "components": [{"domain": "lab", "code_system": "LOINC", "codes": ["4548-4"],
                             "lab_threshold": ">= 6.5", "label": "HbA1c"},
                            {"domain": "drug", "code_system": "RxNorm", "codes": ["metformin", "st john's wort"], "label": "Rx"}]},
        ],
        "exclusions": [{"domain": "diagnosis", "code_system": "ICD10CM", "codes": ["O24"], "label": "Crohn's; gestational"}],
    })
    sql = omop_sql(alg)
    assert "visit_concept_id IN (9201, 262)" in sql and "visit_concept_id IN (9202)" in sql
    assert "LIKE 'E11%'" in sql
    assert "MAX(b.event_date) - a.event_date >= 30" in sql
    assert "COUNT(DISTINCT b.comp) = 2" in sql
    assert "m.value_as_number >= 6.5" in sql
    assert "NOT EXISTS (SELECT 1 FROM excl_1" in sql
    assert "observation_period_start_date <= c.index_date - 365" in sql
    assert "'st john''s wort'" in sql
    assert "r3_hits" in sql and sql.count("UNION ALL SELECT person_id, index_date") == 2


def test_missing_codes_emit_todo_not_wildcard():
    alg = Algorithm.from_dict({"name": "x", "rules": [{"components": [
        {"domain": "diagnosis", "code_system": "ICD10CM", "codes": [], "label": "RA diagnosis"}]}]})
    sql = omop_sql(alg)
    assert "TODO: codes not reported in the source for: RA diagnosis" in sql
    assert "not reported" in pseudocode(alg)
