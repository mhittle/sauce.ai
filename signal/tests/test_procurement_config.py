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
