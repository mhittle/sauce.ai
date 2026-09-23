from app.literature import (Literature, europepmc_query, fulltext_from_jats, merge, parse_europepmc_json,
                            parse_pubmed_xml, pubmed_query)
from app.store import Store
from tests.fakes import FULLTEXT, efetch_xml, fake_http, make_settings


def test_queries_cover_condition_method_validation_and_data():
    q = pubmed_query("multiple sclerosis", ["MS"])
    assert '"multiple sclerosis"[MeSH Terms]' in q and '"MS"[tiab]' in q
    assert "validat*[tiab]" in q and '"positive predictive value"[tiab]' in q
    assert '"Administrative Claims, Healthcare"[MeSH Terms]' in q
    assert q.count(" AND ") == 3
    e = europepmc_query("multiple sclerosis")
    assert "*" not in e and "SRC:MED" in e


def test_parse_pubmed_xml():
    [s] = parse_pubmed_xml(efetch_xml(["111"]))
    assert s.pmid == "111" and s.pmcid == "PMC999" and s.doi == "10.1212/fake.111"
    assert s.year == 2019 and s.journal == "Neurology"
    assert s.authors.startswith("Culpepper WJ")
    assert s.url == "https://pubmed.ncbi.nlm.nih.gov/111/"
    assert s.citation().startswith("Culpepper WJ et al. Validation of an algorithm")


def test_parse_europepmc_and_merge_dedupes_by_pmid_doi_title():
    found, oa = parse_europepmc_json(fake_http("https://x/search", {}))
    assert oa == {"PMC999": True}
    assert found[1].abstract == "We reviewed  40  studies."
    pool = {}
    assert merge(pool, parse_pubmed_xml(efetch_xml(["111", "222"]))) == 2
    assert merge(pool, found) == 1          # 111 duplicate, 444 new
    assert len(pool) == 3


def test_fulltext_keeps_results_and_tables_drops_funding():
    t = fulltext_from_jats(FULLTEXT)
    assert "sensitivity of 92.1% (95% CI 88.0-95.0)" in t
    assert "[TABLE] Table 2 accuracy" in t and "3 claims / 1 yr | 92.1" in t
    assert "NMSS grant" not in t
    assert fulltext_from_jats("<not xml") == ""


def test_find_title_rejects_unresolvable_and_snowball_filters_titles():
    lit = Literature(make_settings(), http_get=fake_http)
    assert lit.find_title("A fabricated paper about phenotypes") is None
    hit = lit.find_title("Validation of an algorithm for identifying MS cases in administrative health claims datasets")
    assert hit and hit.pmid == "111"
    assert lit.snowball(hit) == ["555", "111"]   # irrelevant title and non-PubMed source filtered out
    assert hit.cited_by == 250


def test_http_cache_avoids_refetch():
    calls = []

    def counting(url, params):
        calls.append(url)
        return fake_http(url, params)
    store = Store(":memory:")
    lit = Literature(make_settings(), http_get=counting, cache=store)
    lit.pubmed_search("x")
    lit.pubmed_search("x")
    assert len(calls) == 1


def test_quota_429_fails_fast(monkeypatch):
    import time as _time

    import pytest

    from app import literature

    class R:
        status_code, headers, text = 429, {"Retry-After": "19681"}, ""
    calls = []
    monkeypatch.setattr(literature.requests, "get", lambda *a, **k: calls.append(1) or R())
    t0 = _time.time()
    with pytest.raises(RuntimeError):
        literature.requests_get("https://example.org/x", {})
    assert len(calls) == 1 and _time.time() - t0 < 1
