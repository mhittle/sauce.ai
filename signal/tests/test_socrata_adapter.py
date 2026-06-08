from app.adapters.registry import build_adapter, supported_source_types
from app.adapters.socrata import SocrataAdapter


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
    """Returns one full page then an empty page to end pagination."""
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return FakeResp(self.pages.pop(0) if self.pages else [])


JURIS = {
    "platform_domain": "data.example.org",
    "dataset_id": "abcd-1234",
    "field_map": {"permit_id": "id", "valuation": "cost"},
    "adapter_config": {"page_size": 2},
}


def test_socrata_paginates_and_normalizes():
    page1 = [{"id": "A", "cost": "100"}, {"id": "B", "cost": "200"}]
    page2 = [{"id": "C", "cost": "300"}]
    sess = FakeSession([page1, page2, []])
    adapter = SocrataAdapter(JURIS, app_token="tok", session=sess)
    results = list(adapter.pull())
    assert [r.permit_id for r in results] == ["A", "B", "C"]
    assert results[0].valuation == 100.0
    # app token forwarded as header
    assert sess.calls[0][2] == {"X-App-Token": "tok"}


def test_socrata_base_url():
    adapter = SocrataAdapter(JURIS)
    assert adapter.base_url == "https://data.example.org/resource/abcd-1234.json"


def test_registry_routes_socrata():
    adapter = build_adapter({"source_type": "socrata", **JURIS})
    assert isinstance(adapter, SocrataAdapter)
    assert "socrata" in supported_source_types()
    assert "paid" in supported_source_types()
