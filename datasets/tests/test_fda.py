from types import SimpleNamespace as NS

from app import fda
from app.store import Store


class FakeHTTP:
    def __init__(self, status, body=None):
        self.status, self.body, self.urls = status, body, []

    def get(self, url, **kw):
        self.urls.append(url)
        return NS(status_code=self.status, json=lambda: self.body, text="")


def test_build_search_uses_literal_plus_or():
    assert fda.build_search(["Pneumothorax", "chest x-ray", ""]) == \
        'device_name:"pneumothorax"+device_name:"chest+x-ray"'
    assert fda.build_search([]) is None


def test_count_parses_total_and_404_is_zero():
    ok = FakeHTTP(200, {"meta": {"results": {"total": 42}}})
    assert fda.count_510k(["stroke"], session=ok) == 42
    assert "search=device_name:\"stroke\"" in ok.urls[0]
    assert fda.count_510k(["zzz"], session=FakeHTTP(404)) == 0
    assert fda.count_510k(["x"], session=FakeHTTP(500)) is None


def test_refresh_condition_skips_short_terms(tmp_path):
    s = Store(tmp_path / "c.db")
    s.upsert_condition("multiple sclerosis", synonyms=["ms"], fda_terms=["ms", "white matter"])
    http = FakeHTTP(200, {"meta": {"results": {"total": 7}}})
    assert fda.refresh_condition(s, "Multiple Sclerosis", session=http) == 7
    assert '"ms"' not in http.urls[0] and "white+matter" in http.urls[0]
    assert s.get_condition("multiple sclerosis")["fda_510k_count"] == 7
