"""Offline tests for the Crossref / PubMed / Europe PMC resolvers.

A fake `session` routes each URL to a canned payload so precedence and
fallbacks are exercised without network."""
import json

import requests

from app import claim_sources as cs

CROSSREF_ITEM = {
    "DOI": "10.1056/NEJMoa2034577",
    "title": ["Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine"],
    "container-title": ["New England Journal of Medicine"],
    "issued": {"date-parts": [[2020, 12, 31]]},
    "author": [{"family": "Polack", "given": "Fernando P."}, {"family": "Thomas"}],
    "type": "journal-article",
    "URL": "https://doi.org/10.1056/nejmoa2034577",
}

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle>
  <MedlineCitation><PMID>33301246</PMID>
   <Article>
    <Journal><Title>The New England journal of medicine</Title>
      <JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
    <ArticleTitle>Safety and Efficacy of the <i>BNT162b2</i> mRNA Covid-19 Vaccine.</ArticleTitle>
    <Abstract>
      <AbstractText Label="BACKGROUND">Severe acute respiratory syndrome.</AbstractText>
      <AbstractText Label="RESULTS">A total of 43,548 participants underwent randomization.</AbstractText>
    </Abstract>
    <AuthorList><Author><LastName>Polack</LastName></Author><Author><LastName>Thomas</LastName></Author></AuthorList>
    <PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
   </Article>
  </MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1056/NEJMoa2034577</ArticleId></ArticleIdList></PubmedData>
 </PubmedArticle>
</PubmedArticleSet>"""

EUROPEPMC = {
    "resultList": {"result": [{
        "id": "33301246", "source": "MED", "pmid": "33301246",
        "doi": "10.1056/nejmoa2034577",
        "title": "Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine.",
        "journalTitle": "N Engl J Med", "pubYear": "2020",
        "abstractText": "<p>Background: Severe acute respiratory syndrome.</p> Results: A total of 43,548 participants.",
        "authorString": "Polack FP, Thomas SJ.",
        "pubTypeList": {"pubType": ["Journal Article", "Randomized Controlled Trial"]},
    }]}
}


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Routes by (url substring) -> response. Records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), headers))
        for key, resp in self.routes:
            if key in url:
                if callable(resp):
                    return resp(url, params)
                return resp
        return FakeResp(status=404)


def _routes(crossref_ok=True, europepmc_ok=True, pubmed_ok=True, search_items=None,
            esearch_ids=None):
    routes = []
    routes.append((cs.CROSSREF_WORKS + "/10.", FakeResp(payload={"message": CROSSREF_ITEM})
                   if crossref_ok else FakeResp(status=404)))
    routes.append((cs.CROSSREF_WORKS, FakeResp(payload={"message": {"items": search_items or []}})))
    routes.append((cs.EUROPEPMC_SEARCH, FakeResp(payload=EUROPEPMC) if europepmc_ok
                   else FakeResp(payload={"resultList": {"result": []}})))
    routes.append((cs.PUBMED_ESEARCH, FakeResp(payload={"esearchresult": {"idlist": esearch_ids or []}})))
    routes.append((cs.PUBMED_EFETCH, FakeResp(text=PUBMED_XML) if pubmed_ok else FakeResp(status=500)))
    return routes


def test_user_agent_carries_contact():
    assert "mailto:me@example.org" in cs.user_agent("me@example.org")
    assert "sauce.ai-claim" in cs.user_agent("")


def test_crossref_work_parses_and_fills_abstract_from_europepmc():
    sess = FakeSession(_routes())
    study = cs.resolve_study({"doi": "https://doi.org/10.1056/NEJMoa2034577"},
                             session=sess, contact_email="me@example.org")
    assert study["doi"] == "10.1056/nejmoa2034577"
    assert study["title"].startswith("Safety and Efficacy")
    assert study["journal"] == "New England Journal of Medicine"
    assert study["year"] == 2020
    assert study["first_author"] == "Polack"
    assert study["is_preprint"] is False
    assert study["pmid"] == "33301246"
    assert "43,548 participants" in study["abstract"]
    assert "<p>" not in study["abstract"]
    assert study["resolver"] == "crossref+europepmc"
    urls = [c[0] for c in sess.calls]
    assert urls[0].startswith(cs.CROSSREF_WORKS + "/10.1056")
    assert cs.EUROPEPMC_SEARCH in urls[1]
    assert all("mailto:me@example.org" in c[2]["User-Agent"] for c in sess.calls)


def test_doi_falls_back_to_pubmed_when_europepmc_empty():
    sess = FakeSession(_routes(europepmc_ok=False, esearch_ids=["33301246"]))
    study = cs.resolve_study({"doi": "10.1056/NEJMoa2034577"}, session=sess)
    assert study["pmid"] == "33301246"
    assert study["abstract"].startswith("Background: Severe acute")
    assert "Results: A total of 43,548" in study["abstract"]
    esearch = [c for c in sess.calls if cs.PUBMED_ESEARCH in c[0]][0]
    assert esearch[1]["term"] == "10.1056/nejmoa2034577[AID]"


def test_doi_unknown_to_crossref_tries_europepmc_then_gives_up():
    sess = FakeSession(_routes(crossref_ok=False, europepmc_ok=False))
    assert cs.resolve_study({"doi": "10.9999/nothing"}, session=sess) is None


def test_pmid_path_uses_pubmed_directly():
    sess = FakeSession(_routes())
    study = cs.resolve_study({"pmid": "PMID: 33301246"}, session=sess)
    assert study["resolver"] == "pubmed"
    assert study["doi"] == "10.1056/nejmoa2034577"
    assert study["publication_types"] == ["Randomized Controlled Trial"]
    assert study["title"] == "Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine."
    assert cs.CROSSREF_WORKS not in " ".join(c[0] for c in sess.calls)


def test_bibliographic_search_requires_plausible_match():
    ids = {"title": "BNT162b2 mRNA Covid-19 vaccine safety and efficacy",
           "first_author": "Fernando Polack", "journal": "NEJM"}
    sess = FakeSession(_routes(search_items=[CROSSREF_ITEM]))
    study = cs.resolve_study(ids, session=sess)
    assert study and study["doi"] == "10.1056/nejmoa2034577"
    search = [c for c in sess.calls if c[0] == cs.CROSSREF_WORKS][0]
    assert "query.bibliographic" in search[1]

    wrong = dict(CROSSREF_ITEM, title=["Something entirely different about fish"],
                 author=[{"family": "Nobody"}])
    sess = FakeSession(_routes(search_items=[wrong]))
    assert cs.resolve_study({"title": "BNT162b2 mRNA Covid-19 vaccine safety and efficacy"},
                            session=sess) is None


def test_bibliographic_falls_through_to_pubmed_search():
    ids = {"first_author": "Polack", "journal": "New England Journal of Medicine"}
    sess = FakeSession(_routes(search_items=[], esearch_ids=["33301246"]))
    study = cs.resolve_study(ids, session=sess)
    assert study and study["pmid"] == "33301246"
    esearch = [c for c in sess.calls if cs.PUBMED_ESEARCH in c[0]][0]
    assert "Polack[Author]" in esearch[1]["term"]
    assert "[Journal]" in esearch[1]["term"]


def test_nothing_to_go_on_returns_none_without_network():
    sess = FakeSession(_routes())
    assert cs.resolve_study({}, session=sess) is None
    assert cs.resolve_study({"doi": None, "title": "  "}, session=sess) is None
    assert sess.calls == []


def test_plausible_match_rules():
    study = {"title": "Aspirin and myocardial infarction in older adults",
             "authors": ["Smith", "Jones"], "journal": "JAMA", "year": 2021}
    assert cs.plausible_match({"title": "aspirin myocardial infarction older adults"}, study)
    assert cs.plausible_match({"first_author": "Dr. Jane Jones"}, study)
    assert not cs.plausible_match({"first_author": "Jones", "journal": "Lancet"}, study)
    assert cs.plausible_match({"first_author": "Jones", "journal": "Journal of the American Medical Association"}, study)
    assert cs.plausible_match({"first_author": "Jones", "journal": "J Am Med Assoc"}, study)
    assert not cs.plausible_match({"first_author": "Jones", "year": 2015}, study)
    assert cs.plausible_match({"first_author": "Jones", "year": 2022}, study)
    assert not cs.plausible_match({"journal": "JAMA"}, study)
    assert not cs.plausible_match({}, study)
    assert not cs.plausible_match({"title": "x"}, None)


def test_network_errors_are_swallowed():
    class Boom:
        def get(self, *a, **k):
            raise requests.ConnectionError("down")
    assert cs.crossref_work("10.1/x", session=Boom()) is None
    assert cs.pubmed_search("x[AID]", session=Boom()) == []
    assert cs.europepmc_lookup(doi="10.1/x", session=Boom()) is None
    assert cs.resolve_study({"doi": "10.1/x"}, session=Boom()) is None


def test_bad_payloads_are_tolerated():
    sess = FakeSession([
        (cs.CROSSREF_WORKS + "/10.", FakeResp(payload=None, text="<html>")),
        (cs.EUROPEPMC_SEARCH, FakeResp(payload={"weird": 1})),
        (cs.PUBMED_EFETCH, FakeResp(text="not xml")),
        (cs.PUBMED_ESEARCH, FakeResp(payload={})),
    ])
    assert cs.resolve_study({"doi": "10.1/x"}, session=sess) is None
    assert cs.parse_pubmed_xml("<PubmedArticleSet/>") is None
    assert cs.pubmed_fetch("bad", session=sess) is None


def test_crossref_preprint_and_jats_abstract():
    item = dict(CROSSREF_ITEM, type="posted-content", subtype="preprint",
                **{"container-title": [], "abstract": "<jats:p>Objective: We tested <b>x</b>.</jats:p>"})
    study = cs._study_from_crossref(item)
    assert study["is_preprint"] is True
    assert study["abstract"] == "Objective: We tested x ."
    assert study["journal"] is None


def test_pubmed_term_shapes():
    assert cs.pubmed_term({"doi": "10.1000/ABC"}) == "10.1000/abc[AID]"
    term = cs.pubmed_term({"title": "The effect of coffee on dementia risk", "first_author": "Lee"})
    assert "coffee[Title]" in term and "dementia[Title]" in term and "Lee[Author]" in term
    assert cs.pubmed_term({}) == ""
    assert json.dumps(cs.bibliographic_query({"title": "A", "journal": "B", "year": 2020})) == '"A B 2020"'
