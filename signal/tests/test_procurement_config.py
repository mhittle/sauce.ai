from datetime import date

import pytest

from app.adapters.solicitations.config_source import (build_config_adapter,
                                                      JsonConfigAdapter)


class FakeResp:
    def __init__(self, *, json_data=None, text=""):
        self._json = json_data
        self.text = text
        self.status_code = 200

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, resp):
        self.resp = resp

    def get(self, url, timeout=None, headers=None):
        return self.resp


JSON_SOURCE = {
    "slug": "demo-json", "state": "GA", "platform": "json",
    "list_url": "https://x/api/opps",
    "config": {
        "records_path": "data.opportunities",
        "fields": {
            "source_id": "id", "title": "name", "agency": "org.name",
            "due_date": "dates.close", "source_url": "links.web",
            "estimated_value": "value",
        },
        "documents": {"path": "files", "name": "fileName", "url": "url"},
    },
}

JSON_BODY = {"data": {"opportunities": [
    {"id": "OPP-1", "name": "Multifamily Renovation – Housing Authority",
     "org": {"name": "Atlanta Housing"}, "dates": {"close": "2026-07-15"},
     "links": {"web": "https://x/opp/OPP-1"}, "value": "$2,500,000",
     "files": [{"fileName": "plans.pdf", "url": "https://x/files/plans.pdf"}]},
    {"id": "OPP-2", "name": "Road Resurfacing", "org": {"name": "DOT"},
     "dates": {"close": "2026-08-01"}, "links": {"web": "https://x/opp/OPP-2"},
     "value": None, "files": []},
]}}


def test_json_config_extracts_and_normalizes():
    adapter = JsonConfigAdapter(JSON_SOURCE, session=FakeSession(FakeResp(json_data=JSON_BODY)))
    out = list(adapter.pull())
    assert [s.source_id for s in out] == ["OPP-1", "OPP-2"]
    first = out[0]
    assert first.title.startswith("Multifamily")
    assert first.agency == "Atlanta Housing"
    assert first.state == "GA"                  # default from source
    assert first.due_date == date(2026, 7, 15)
    assert first.estimated_value == 2500000.0   # currency coerced
    assert len(first.documents) == 1 and first.documents[0].name == "plans.pdf"
    assert out[1].documents == []


def test_build_config_adapter_dispatches():
    assert isinstance(build_config_adapter(JSON_SOURCE), JsonConfigAdapter)
    with pytest.raises(ValueError):
        build_config_adapter({"platform": "weird", "list_url": "x"})


HTML_SOURCE = {
    "slug": "demo-html", "state": "GA", "platform": "html",
    "list_url": "https://x/bids",
    "config": {
        "base_url": "https://x/",
        "row_selector": "tr.bid",
        "fields": {
            "title": {"selector": "a.title", "attr": "text"},
            "source_url": {"selector": "a.title", "attr": "href"},
            "source_id": {"selector": "a.title", "attr": "href", "regex": "id=(\\d+)"},
            "due_date": {"selector": "td.due", "attr": "text"},
        },
        "documents": {"selector": "a.doc"},
    },
}

HTML_BODY = """
<table><tbody>
  <tr class="bid"><td><a class="title" href="/opp?id=42">New Apartments TI</a></td>
      <td class="due">07/20/2026</td>
      <td><a class="doc" href="/files/a.pdf">A</a><a class="doc" href="/files/b.pdf">B</a></td></tr>
  <tr class="bid"><td><a class="title" href="/opp?id=43">Sidewalk Repair</a></td>
      <td class="due">08/05/2026</td><td></td></tr>
</tbody></table>
"""


# Real CivicPlus "Bids.aspx" row shape (validated live against Gainesville/
# Marietta GA, 2026-06-09). Locks the pattern that generalizes across cities.
CIVICPLUS_SOURCE = {
    "slug": "ga-civicplus", "state": "GA", "platform": "html",
    "list_url": "https://city.example/Bids.aspx",
    "config": {
        "base_url": "https://city.example/",
        "row_selector": ".listItemsRow.bid",
        "fields": {
            "title": {"selector": ".bidTitle a", "attr": "text"},
            "source_url": {"selector": ".bidTitle a", "attr": "href"},
            "source_id": {"selector": ".bidTitle a", "attr": "href", "regex": "bidID=(\\d+)"},
            "status": {"selector": ".bidStatus div:nth-of-type(2) span", "attr": "text"},
            "due_date": {"selector": ".bidStatus div:nth-of-type(2) span:nth-of-type(2)", "attr": "text"},
        },
    },
}

CIVICPLUS_HTML = """
<div class="listItemsRow bid">
  <div class="bidTitle"><span><a href="bids.aspx?bidID=177">Gainesville Connector Trails</a></span>
    <br/><span><strong>Bid No.</strong> RFB-26-123</span></div>
  <div class="bidStatus">
    <div><span>Status:</span><br/><span>Closes:</span></div>
    <div><span>Open</span><br/><span>6/25/2026 2:00 PM</span></div>
  </div>
</div>
<div class="listItemsRow">ignored non-bid row</div>
"""


def test_civicplus_pattern_live_shape():
    pytest.importorskip("bs4")
    from app.adapters.solicitations.config_source import HtmlConfigAdapter
    out = list(HtmlConfigAdapter(
        CIVICPLUS_SOURCE, session=FakeSession(FakeResp(text=CIVICPLUS_HTML))).pull())
    assert len(out) == 1                       # only the .bid row
    s = out[0]
    assert s.source_id == "177"
    assert s.title == "Gainesville Connector Trails"
    assert s.source_url == "https://city.example/bids.aspx?bidID=177"
    assert s.status == "Open"
    assert s.due_date == date(2026, 6, 25)     # "6/25/2026 2:00 PM" parsed


class RoutingSession:
    """Returns detail HTML for bid-detail URLs, list HTML otherwise."""
    def __init__(self, list_html, detail_html):
        self.list_html, self.detail_html = list_html, detail_html

    def get(self, url, timeout=None, headers=None):
        html = self.detail_html if "bidID=" in url else self.list_html
        return FakeResp(text=html)


CIVICPLUS_DETAIL_HTML = """
<div class="relatedDocuments">
  <a href="/DocumentCenter/View/15502">Connector Trails - Compiled Plans</a>
  <a href="/DocumentCenter/View/15550">Addendum No 1</a>
  <a href="https://elsewhere/other">unrelated</a>
</div>
"""


def test_civicplus_detail_page_document_fetch():
    pytest.importorskip("bs4")
    src = {"slug": "x", "state": "GA", "platform": "civicplus", "domain": "city.example"}
    sess = RoutingSession(CIVICPLUS_HTML, CIVICPLUS_DETAIL_HTML)
    out = list(build_config_adapter(src, session=sess).pull())
    assert len(out) == 1
    docs = out[0].documents
    assert len(docs) == 2                       # only the DocumentCenter links
    assert docs[0].url == "https://city.example/DocumentCenter/View/15502"
    assert docs[0].doc_type == "plans"          # "...Compiled Plans"
    assert docs[1].doc_type == "addendum"


def test_civicplus_platform_shortcut():
    # Compact entry (slug + domain) synthesizes the validated CivicPlus config.
    pytest.importorskip("bs4")
    src = {"slug": "x", "state": "GA", "platform": "civicplus", "domain": "city.example"}
    out = list(build_config_adapter(src, session=FakeSession(FakeResp(text=CIVICPLUS_HTML))).pull())
    assert len(out) == 1 and out[0].source_id == "177"
    assert out[0].source_url == "https://city.example/bids.aspx?bidID=177"
    assert out[0].due_date == date(2026, 6, 25)


def test_seed_procurement_sources_valid():
    import json
    import pathlib
    data = json.loads((pathlib.Path(__file__).resolve().parents[1]
                       / "seed" / "procurement_sources.json").read_text())
    slugs = [s["slug"] for s in data]
    assert len(slugs) == len(set(slugs)), "duplicate source slug"
    assert len(data) >= 200
    for s in data:
        assert s["platform"] in ("civicplus", "json", "html")
        if s["platform"] == "civicplus":
            assert s.get("domain"), f"{s['slug']} missing domain"
        else:
            assert s.get("list_url"), f"{s['slug']} missing list_url"


def test_html_config_extracts_rows_fields_and_docs():
    pytest.importorskip("bs4")
    from app.adapters.solicitations.config_source import HtmlConfigAdapter
    adapter = HtmlConfigAdapter(HTML_SOURCE, session=FakeSession(FakeResp(text=HTML_BODY)))
    out = list(adapter.pull())
    assert [s.source_id for s in out] == ["42", "43"]
    assert out[0].title == "New Apartments TI"
    assert out[0].source_url == "https://x/opp?id=42"   # relative resolved
    assert out[0].due_date == date(2026, 7, 20)
    assert len(out[0].documents) == 2
    assert out[0].documents[0].url == "https://x/files/a.pdf"
    assert out[1].documents == []
