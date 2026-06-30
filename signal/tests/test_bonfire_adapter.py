from datetime import date

from app.adapters.solicitations.bonfire import BonfireAdapter
from app.adapters.solicitations.registry import (build_solicitation_adapter,
                                                 supported_source_types)


class FakeResp:
    def __init__(self, data, ctype="application/json"):
        self._data = data
        self.status_code = 200
        self.headers = {"content-type": ctype}

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    """Returns the portal page (ignored) then the JSON payload per agency."""
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def get(self, url, timeout=None):
        if url.endswith("getOpenPublicOpportunitiesSectionData"):
            return FakeResp({"success": True, "payload": self.payload})
        return FakeResp({}, ctype="text/html")  # portal seed page (ignored)


_PAYLOAD = {
    "projects": {
        "242023": {
            "ProjectID": "242023", "ReferenceID": "CP25-07",
            "ProjectName": "Medical Examiner's Office Storage Building Addition",
            "DateClose": "2026-07-28 21:00:00", "DepartmentID": "3812",
            "ProjectStatusID": "2",
        },
    },
    "departments": {"3812": {"DepartmentName": "PWA"}},
}


def test_registered():
    assert "bonfire" in supported_source_types()
    assert isinstance(build_solicitation_adapter("bonfire"), BonfireAdapter)


def test_pull_normalizes_open_opportunity():
    a = BonfireAdapter(config={"agencies": ["ventura"]},
                       session=FakeSession(_PAYLOAD))
    norms = list(a.pull())
    assert len(norms) == 1
    n = norms[0]
    assert n.source_id == "ventura-242023"          # agency-prefixed → unique
    assert n.state == "CA"
    assert n.agency == "PWA"                          # dept join resolved
    assert n.due_date == date(2026, 7, 28)
    assert n.status == "open"
    assert "id=242023" in n.source_url
    assert "Medical Examiner" in n.title


def test_bad_record_skipped():
    a = BonfireAdapter(session=FakeSession(_PAYLOAD))
    assert a.parse({"_agency": "x"}) is None          # no ProjectID
    assert a.parse({"ProjectID": "1"}) is None        # no agency
