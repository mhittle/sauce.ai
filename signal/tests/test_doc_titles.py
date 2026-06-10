from app.ingest.classify import _cd_filename, _meaningful, _pick_title
from app.ingest.pdftext import _clean_title, _first_heading, extract_pdf_meta


class FakeResp:
    def __init__(self, cd):
        self.headers = {"Content-Disposition": cd} if cd else {}


def test_meaningful_rejects_generic():
    assert _meaningful("download") is None
    assert _meaningful("") is None
    assert _meaningful("15501") is None
    assert _meaningful("Compiled Plans") == "Compiled Plans"


def test_pick_title_prefers_link_name():
    assert _pick_title("Gainesville Connector Trails - Compiled Plans",
                       "whatever.pdf", "Storm", "https://x/View/1") \
        == "Gainesville Connector Trails - Compiled Plans"


def test_pick_title_falls_back_to_download_filename():
    # SAM-style: link name is generic "download" -> use the CD filename.
    assert _pick_title("download", "RFB 26023 Energy Services Program",
                       None, "https://x/files/abc/download") \
        == "RFB 26023 Energy Services Program"


def test_pick_title_falls_back_to_url_basename():
    assert _pick_title("download", None, None,
                       "https://x/files/Bid-Documents-2026.pdf") \
        == "Bid-Documents-2026"


def test_cd_filename_parsing():
    assert _cd_filename(FakeResp('inline; filename="Bid 26022 Trails.pdf"')) \
        == "Bid 26022 Trails"
    assert _cd_filename(FakeResp("attachment; filename*=UTF-8''Plans%20Set.pdf")) \
        == "Plans Set"
    assert _cd_filename(FakeResp("")) is None


def test_clean_title_and_first_heading():
    assert _clean_title("  CONTRACT  DOCUMENTS  ") == "CONTRACT DOCUMENTS"
    assert _clean_title("12") is None
    assert _first_heading("x\nGainesville Connector Trails\nmore") \
        == "Gainesville Connector Trails"


def test_extract_pdf_meta_non_pdf():
    assert extract_pdf_meta(b"not a pdf") == (None, "")
    assert extract_pdf_meta(b"") == (None, "")
