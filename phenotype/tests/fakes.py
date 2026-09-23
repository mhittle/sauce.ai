"""Offline stand-ins for the literature APIs and the models."""
import json
import re

from app.catalog import EXEMPLAR
from app.config import Settings
from app.providers import MockModel

ARTICLES = {
    "111": dict(title="Validation of an algorithm for identifying MS cases in administrative health claims datasets",
                abstract="OBJECTIVE: To validate claims algorithms for MS. RESULTS: Three or more MS-related claims "
                         "within one year performed best.",
                journal="Neurology", year="2019", doi="10.1212/fake.111", pmc="PMC999",
                authors=[("Culpepper", "WJ"), ("Marrie", "RA")]),
    "222": dict(title="Accuracy of administrative case definitions for multiple sclerosis in Manitoba",
                abstract="Using physician claims and hospital abstracts, 3 claims within 1 year had a "
                         "sensitivity of 90.4% (95% CI 86.0 to 93.5) and specificity of 97.2%. "
                         "One claim ever had lower accuracy.",
                journal="Mult Scler", year="2016", doi="10.1/fake.222", pmc="",
                authors=[("Marrie", "RA")]),
    "333": dict(title="Adherence to disease-modifying therapy in MS", abstract="Adherence was low.",
                journal="J Neurol", year="2020", doi="", pmc="", authors=[("Smith", "A")]),
    "555": dict(title="Validation of an MS algorithm in Medicare claims",
                abstract="Among 400 reviewed charts the >=3 claims in 1 year definition had "
                         "a positive predictive value of 94% and specificity of 98.5%.",
                journal="Pharmacoepidemiol Drug Saf", year="2021", doi="", pmc="", authors=[("Lee", "K")]),
}

FULLTEXT = """<article><front><article-meta><title-group><article-title>x</article-title></title-group></article-meta></front>
<body><sec><title>Results</title><p>In the VA dataset the algorithm had a sensitivity of 92.1% (95% CI 88.0-95.0)
and a PPV of 96.0% (95% CI 93.5-97.6).</p></sec><sec><title>Funding</title><p>NMSS grant.</p></sec>
<table-wrap><caption>Table 2 accuracy</caption><table><tr><td>Algorithm</td><td>Sens</td></tr>
<tr><td>3 claims / 1 yr</td><td>92.1</td></tr></table></table-wrap></body></article>"""


def efetch_xml(ids):
    out = []
    for i in ids:
        a = ARTICLES.get(i)
        if not a:
            continue
        auth = "".join(f"<Author><LastName>{l}</LastName><Initials>{n}</Initials></Author>" for l, n in a["authors"])
        pmc = f'<ArticleId IdType="pmc">{a["pmc"]}</ArticleId>' if a["pmc"] else ""
        doi = f'<ArticleId IdType="doi">{a["doi"]}</ArticleId>' if a["doi"] else ""
        out.append(f"""<PubmedArticle><MedlineCitation><PMID>{i}</PMID><Article>
<Journal><JournalIssue><PubDate><Year>{a['year']}</Year></PubDate></JournalIssue><ISOAbbreviation>{a['journal']}</ISOAbbreviation></Journal>
<ArticleTitle>{a['title']}</ArticleTitle><Abstract><AbstractText>{a['abstract']}</AbstractText></Abstract>
<AuthorList>{auth}</AuthorList></Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="pubmed">{i}</ArticleId>{doi}{pmc}</ArticleIdList></PubmedData></PubmedArticle>""")
    return "<PubmedArticleSet>" + "".join(out) + "</PubmedArticleSet>"


def fake_http(url, params):
    if url.endswith("esearch.fcgi"):
        term = params["term"]
        if "fabricated" in term:
            ids = []
        elif "[ti]" in term:
            ids = ["111"]
        else:
            ids = ["111", "222", "333"]
        return json.dumps({"esearchresult": {"idlist": ids}})
    if url.endswith("efetch.fcgi"):
        return efetch_xml(params["id"].split(","))
    if url.endswith("/search"):
        return json.dumps({"resultList": {"result": [
            {"pmid": "111", "pmcid": "PMC999", "doi": "10.1212/fake.111", "isOpenAccess": "Y",
             "title": ARTICLES["111"]["title"], "pubYear": "2019", "authorString": "Culpepper WJ, Marrie RA."},
            {"pmid": "444", "doi": "10.1/fake.444", "title": "Case definitions for MS: a systematic review",
             "pubYear": "2018", "authorString": "Doe J.", "abstractText": "We reviewed <i>40</i> studies.",
             "journalTitle": "Neuroepidemiology"}]}})
    if url.endswith("/fullTextXML"):
        return FULLTEXT if "PMC999" in url else ""
    if url.endswith("/citations"):
        if "/MED/111/" not in url:
            return json.dumps({"hitCount": 0, "citationList": {"citation": []}})
        return json.dumps({"hitCount": 250, "citationList": {"citation": [
            {"source": "MED", "id": "555", "title": ARTICLES["555"]["title"]},
            {"source": "MED", "id": "666", "title": "Cost of MS care"},
            {"source": "PPR", "id": "PPR1", "title": "Validation preprint"}]}})
    if url.endswith("/references"):
        return json.dumps({"hitCount": 1, "referenceList": {"reference": [
            {"source": "MED", "id": "111", "title": ARTICLES["111"]["title"]}]}})
    raise AssertionError(f"unexpected URL {url}")


def screen_responder(system, messages):
    text = messages[-1]["content"]
    out = []
    for m in re.finditer(r"^\[(\d+)\] (.*)$", text, re.M):
        title = m.group(2)
        label = ("review" if "review" in title.lower() else
                 "validation" if re.search(r"validation|accuracy", title, re.I) else "exclude")
        out.append({"id": int(m.group(1)), "label": label, "reason": "test"})
    return json.dumps({"decisions": out})


MS = EXEMPLAR["algorithm"]
ONE_CLAIM = {"name": ">=1 MS claim ever", "summary": "Any single claim.", "data_types": ["claims"],
             "rules": [{"min_events": 1, "components": [
                 {"domain": "diagnosis", "code_system": "ICD10CM", "codes": ["G35"], "label": "MS"}]}]}


def extract_responder(system, messages):
    text = messages[-1]["content"]
    if "PAPERS" in text or "List up to" in text:  # suggestion call
        return json.dumps({"papers": [{"title": ARTICLES["111"]["title"]},
                                      {"title": "A fabricated paper about phenotypes"}]})
    val = lambda **kw: {"reference_standard": "chart_review_criteria", "sampling": "population_random",
                        "blinded": True, "data_type": "claims", **kw}
    if "Validation of an algorithm for identifying MS" in text:
        return json.dumps({"algorithms": [{"role": "developed", "algorithm": MS, "validations": [val(
            dataset="VA", country="United States", n_validated=500, metrics={
                "sensitivity": {"value": 0.921, "lo": 0.88, "hi": 0.95,
                                "quote": "sensitivity of 92.1% (95% CI 88.0-95.0)"},
                "ppv": {"value": 0.96, "lo": 0.935, "hi": 0.976, "quote": "PPV of 96.0% (95% CI 93.5-97.6)"}})]}]})
    if "Manitoba" in text:
        return json.dumps({"algorithms": [
            {"role": "validated_existing", "algorithm": MS, "validations": [val(
                dataset="Manitoba", country="Canada", n_validated=300, external=True, metrics={
                    "sensitivity": {"value": 0.904, "lo": 0.86, "hi": 0.935,
                                    "quote": "sensitivity of 90.4% (95% CI 86.0 to 93.5)"},
                    "specificity": {"value": 0.972, "quote": "specificity of 97.2%"}})]},
            {"role": "developed", "algorithm": ONE_CLAIM, "validations": [val(
                dataset="Manitoba", country="Canada", n_validated=300, reference_standard="self_report",
                metrics={"ppv": {"value": 0.99, "quote": "PPV 99% for one claim"}})]}]})
    if "Medicare" in text:
        return json.dumps({"algorithms": [{"role": "validated_existing", "algorithm": MS, "validations": [val(
            dataset="Medicare 5%", country="United States", n_validated=400, sampling="population_random",
            metrics={"ppv": {"value": 0.94, "quote": "positive predictive value of 94%"},
                     "specificity": {"value": 0.985, "quote": "specificity of 98.5%"}})]}]})
    return json.dumps({"algorithms": []})


def make_mocks():
    return {"mock:screen": MockModel("screen", screen_responder),
            "mock:extract": MockModel("extract", extract_responder)}


def make_settings(**kw):
    base = dict(db_path=":memory:", screen_model="mock:screen", extract_model="mock:extract",
                extract_concurrency=2, worker_threads=1)
    base.update(kw)
    return Settings(**base)
