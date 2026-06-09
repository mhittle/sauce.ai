from datetime import date

from app.adapters.solicitations.base import is_construction
from app.adapters.solicitations.registry import (build_solicitation_adapter,
                                                 supported_source_types)
from app.adapters.solicitations.samgov import SamGovAdapter
from app.adapters.solicitations.scaffolds import TexasESBDAdapter

import pytest


class FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        return FakeResp(self.pages.pop(0) if self.pages else {"opportunitiesData": []})


def _record(**over):
    rec = {
        "noticeId": "abc123",
        "title": "New Commercial Kitchen Build-Out",
        "fullParentPathName": "GSA/PBS/Region 4",
        "naicsCode": "236220",
        "postedDate": "2026-05-01",
        "responseDeadLine": "2026-06-15T17:00:00-04:00",
        "type": "Solicitation",
        "uiLink": "https://sam.gov/opp/abc123/view",
        "placeOfPerformance": {"city": {"name": "Atlanta"}, "state": {"code": "GA"}},
        "resourceLinks": ["https://api.sam.gov/files/v1/x/download",
                          "https://api.sam.gov/files/v1/y/download"],
    }
    rec.update(over)
    return rec


def test_is_construction():
    assert is_construction("236220") is True
    assert is_construction("238160") is True
    assert is_construction("541330") is False   # engineering services, not construction
    assert is_construction(None) is False


def test_parse_maps_fields_and_documents():
    adapter = SamGovAdapter(api_key="k")
    norm = adapter.parse(_record())
    assert norm is not None
    assert norm.source_id == "abc123"
    assert norm.agency == "GSA/PBS/Region 4"
    assert norm.naics == "236220"
    assert norm.state == "GA" and norm.place_city == "Atlanta"
    assert norm.posted_date == date(2026, 5, 1)
    assert norm.due_date == date(2026, 6, 15)
    assert len(norm.documents) == 2
    assert norm.documents[0].url.endswith("/download")


def test_parse_skips_non_construction_and_missing_id():
    adapter = SamGovAdapter(api_key="k")
    assert adapter.parse(_record(naicsCode="541330")) is None
    assert adapter.parse(_record(noticeId=None)) is None


def test_fetch_raw_paginates():
    page1 = {"opportunitiesData": [_record(noticeId="a"), _record(noticeId="b")],
             "totalRecords": 3}
    page2 = {"opportunitiesData": [_record(noticeId="c")], "totalRecords": 3}
    sess = FakeSession([page1, page2])
    adapter = SamGovAdapter(api_key="k", config={"limit": 2}, session=sess)
    got = list(adapter.pull(since=date(2026, 5, 1)))
    assert [s.source_id for s in got] == ["a", "b", "c"]
    # api_key + MM/dd/yyyy dates forwarded
    assert sess.calls[0]["api_key"] == "k"
    assert sess.calls[0]["postedFrom"] == "05/01/2026"


def test_fetch_raw_requires_api_key():
    adapter = SamGovAdapter(api_key=None)
    with pytest.raises(RuntimeError):
        list(adapter.fetch_raw())


def test_registry_routes_and_scaffolds_fail_safe():
    assert isinstance(build_solicitation_adapter("samgov", samgov_api_key="k"),
                      SamGovAdapter)
    for st in ("samgov", "esbd-tx", "vbs-fl", "gpr-ga", "bidnet", "demandstar"):
        assert st in supported_source_types()
    scaffold = build_solicitation_adapter("esbd-tx")
    assert isinstance(scaffold, TexasESBDAdapter)
    with pytest.raises(NotImplementedError):
        list(scaffold.fetch_raw())
