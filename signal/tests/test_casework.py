from app.signals.casework import classify_casework
from app.ingest.pdftext import extract_pdf_text


def test_flags_definite_cabinetry():
    r = classify_casework(
        "Scope includes architectural millwork and plastic-laminate casework, "
        "base cabinets and countertops in the breakroom.")
    assert r["flag"] is True
    assert r["score"] > 0
    assert "casework" in r["matches"] and "millwork" in r["matches"]


def test_flags_on_csi_section_number():
    assert classify_casework("See section 06 41 00 for cabinets.")["flag"] is True
    assert classify_casework("Manufactured casework per 12 35 00.")["flag"] is True


def test_no_flag_for_civil_work():
    r = classify_casework(
        "Gainesville Connector Trails - grading, asphalt paving, storm sewer "
        "and water main replacement.")
    assert r["flag"] is False
    assert r["score"] == 0.0


def test_empty_text():
    r = classify_casework(None)
    assert r == {"flag": False, "score": 0.0, "matches": []}


def test_score_increases_with_more_terms():
    one = classify_casework("casework")["score"]
    many = classify_casework("casework millwork cabinets countertop vanity")["score"]
    assert many > one


def test_extract_pdf_text_handles_non_pdf():
    assert extract_pdf_text(b"this is not a pdf") == ""
    assert extract_pdf_text(b"") == ""
