"""Study resolvers for /claim: Crossref, PubMed E-utilities, Europe PMC.

Deterministic, network-only (no model). `resolve_study(identifiers)` tries,
in order: DOI -> Crossref `works/<doi>`; else PMID -> PubMed efetch; else
Crossref bibliographic search; else PubMed esearch over title / author /
journal. Europe PMC and PubMed fill in the abstract when Crossref has
none. A candidate is accepted only when it plausibly matches what the
article said (title overlap or author surname, no journal / year
contradiction) — never the top hit on faith. `None` means no study
located, which the caller treats as a first-class outcome.

All requests carry a contact User-Agent (Crossref etiquette), an 8 s
timeout, and parse with the stdlib only. `session` is injectable so tests
run offline.
"""
import re
import xml.etree.ElementTree as ET

import requests

from .claim import normalize_doi, normalize_pmid, normalize_ws

CROSSREF_WORKS = "https://api.crossref.org/works"
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

TIMEOUT = 8.0
MAX_CANDIDATES = 3
_PREPRINT_VENUES = ("medrxiv", "biorxiv", "researchsquare", "research square", "ssrn", "arxiv", "preprints.org")
_TAG_RE = re.compile(r"<[^>]+>")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"the", "and", "with", "for", "from", "that", "this", "study", "trial",
                   "among", "effect", "effects", "association", "randomized", "randomised"})


def user_agent(contact_email=""):
    contact = f" (mailto:{contact_email})" if contact_email else ""
    return f"sauce.ai-claim/1.0{contact} https://sauce.ai/news/claim"


def empty_study():
    return {
        "doi": None, "pmid": None, "title": None, "journal": None, "year": None,
        "first_author": None, "authors": [], "abstract": None,
        "is_preprint": False, "resolver": None, "url": None,
        "publication_types": [],
    }


def _get(session, url, params, *, headers, timeout=TIMEOUT):
    sess = session or requests
    try:
        resp = sess.get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    return resp


def _get_json(session, url, params, *, headers):
    resp = _get(session, url, params, headers=headers)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def _strip_tags(text):
    if not text:
        return None
    return normalize_ws(_TAG_RE.sub(" ", text)) or None


def _tokens(text):
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 3 and t not in _STOP}


def _year_of(value):
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


# --- Crossref -------------------------------------------------------------

def _study_from_crossref(item):
    if not isinstance(item, dict):
        return None
    study = empty_study()
    study["doi"] = normalize_doi(item.get("DOI"))
    titles = item.get("title") or []
    study["title"] = _strip_tags(titles[0]) if titles else None
    journals = item.get("container-title") or []
    study["journal"] = normalize_ws(journals[0]) if journals else None
    for key in ("published-print", "published-online", "issued", "created"):
        parts = ((item.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            study["year"] = _year_of(parts[0])
            break
    authors = []
    for a in item.get("author") or []:
        fam = a.get("family") if isinstance(a, dict) else None
        if fam:
            authors.append(normalize_ws(fam))
    study["authors"] = authors
    study["first_author"] = authors[0] if authors else None
    study["abstract"] = _strip_tags(item.get("abstract"))
    ctype = (item.get("type") or "").lower()
    subtype = (item.get("subtype") or "").lower()
    venue = (study["journal"] or "").lower()
    study["is_preprint"] = (
        ctype == "posted-content" or subtype == "preprint"
        or any(v in venue for v in _PREPRINT_VENUES)
    )
    study["url"] = item.get("URL")
    study["resolver"] = "crossref"
    return study if study["doi"] else None


def crossref_work(doi, *, session=None, contact_email=""):
    doi = normalize_doi(doi)
    if not doi:
        return None
    data = _get_json(session, f"{CROSSREF_WORKS}/{doi}", {},
                     headers={"User-Agent": user_agent(contact_email)})
    if not data:
        return None
    return _study_from_crossref(data.get("message"))


def bibliographic_query(identifiers):
    bits = [identifiers.get(k) for k in ("title", "first_author", "journal")]
    bits = [normalize_ws(b) for b in bits if isinstance(b, str) and b.strip()]
    if identifiers.get("year"):
        bits.append(str(identifiers["year"]))
    return " ".join(bits)


def crossref_search(identifiers, *, session=None, contact_email=""):
    query = bibliographic_query(identifiers)
    if not query:
        return None
    data = _get_json(session, CROSSREF_WORKS,
                     {"query.bibliographic": query, "rows": MAX_CANDIDATES},
                     headers={"User-Agent": user_agent(contact_email)})
    if not data:
        return None
    for item in (data.get("message") or {}).get("items") or []:
        study = _study_from_crossref(item)
        if study and plausible_match(identifiers, study):
            return study
    return None


# --- PubMed ---------------------------------------------------------------

def pubmed_term(identifiers):
    doi = normalize_doi(identifiers.get("doi"))
    if doi:
        return f"{doi}[AID]"
    parts = []
    title = identifiers.get("title")
    if isinstance(title, str) and title.strip():
        words = [w for w in _TOKEN_RE.findall(title.lower()) if len(w) >= 4 and w not in _STOP]
        if words:
            parts.append(" ".join(f"{w}[Title]" for w in words[:8]))
    author = identifiers.get("first_author")
    if isinstance(author, str) and author.strip():
        parts.append(f"{normalize_ws(author)}[Author]")
    journal = identifiers.get("journal")
    if isinstance(journal, str) and journal.strip():
        parts.append(f"\"{normalize_ws(journal)}\"[Journal]")
    return " AND ".join(parts)


def pubmed_search(term, *, session=None, contact_email=""):
    if not term:
        return []
    data = _get_json(session, PUBMED_ESEARCH,
                     {"db": "pubmed", "term": term, "retmax": MAX_CANDIDATES,
                      "retmode": "json", "sort": "relevance"},
                     headers={"User-Agent": user_agent(contact_email)})
    if not data:
        return []
    ids = ((data.get("esearchresult") or {}).get("idlist")) or []
    return [normalize_pmid(i) for i in ids if normalize_pmid(i)]


def _text(el):
    return normalize_ws("".join(el.itertext())) if el is not None else None


def parse_pubmed_xml(xml_text):
    """First PubmedArticle in an efetch XML payload -> study dict, or None."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    art = root.find(".//PubmedArticle")
    if art is None:
        return None
    study = empty_study()
    study["pmid"] = normalize_pmid(_text(art.find("./MedlineCitation/PMID")))
    article = art.find("./MedlineCitation/Article")
    if article is None:
        return None
    study["title"] = _text(article.find("./ArticleTitle"))
    chunks = []
    for ab in article.findall("./Abstract/AbstractText"):
        label = ab.get("Label")
        body = _text(ab)
        if not body:
            continue
        chunks.append(f"{label.title()}: {body}" if label else body)
    study["abstract"] = " ".join(chunks) or None
    study["journal"] = _text(article.find("./Journal/Title"))
    year = _text(article.find("./Journal/JournalIssue/PubDate/Year"))
    if not year:
        year = _text(article.find("./Journal/JournalIssue/PubDate/MedlineDate"))
    study["year"] = _year_of(year)
    authors = [_text(a.find("./LastName")) for a in article.findall("./AuthorList/Author")]
    study["authors"] = [a for a in authors if a]
    study["first_author"] = study["authors"][0] if study["authors"] else None
    study["publication_types"] = [
        _text(p) for p in article.findall("./PublicationTypeList/PublicationType") if _text(p)]
    for aid in art.findall("./PubmedData/ArticleIdList/ArticleId"):
        if (aid.get("IdType") or "").lower() == "doi":
            study["doi"] = normalize_doi(_text(aid))
    venue = (study["journal"] or "").lower()
    study["is_preprint"] = (
        "Preprint" in study["publication_types"]
        or any(v in venue for v in _PREPRINT_VENUES)
    )
    study["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{study['pmid']}/" if study["pmid"] else None
    study["resolver"] = "pubmed"
    return study


def pubmed_fetch(pmid, *, session=None, contact_email=""):
    pmid = normalize_pmid(pmid)
    if not pmid:
        return None
    resp = _get(session, PUBMED_EFETCH,
                {"db": "pubmed", "id": pmid, "retmode": "xml"},
                headers={"User-Agent": user_agent(contact_email)})
    if resp is None:
        return None
    return parse_pubmed_xml(resp.text)


# --- Europe PMC -----------------------------------------------------------

def europepmc_lookup(*, doi=None, pmid=None, session=None, contact_email=""):
    doi = normalize_doi(doi)
    pmid = normalize_pmid(pmid)
    if doi:
        query = f'DOI:"{doi}"'
    elif pmid:
        query = f"EXT_ID:{pmid} AND SRC:MED"
    else:
        return None
    data = _get_json(session, EUROPEPMC_SEARCH,
                     {"query": query, "format": "json", "resultType": "core", "pageSize": 1},
                     headers={"User-Agent": user_agent(contact_email)})
    if not data:
        return None
    results = (data.get("resultList") or {}).get("result") or []
    if not results:
        return None
    r = results[0]
    study = empty_study()
    study["doi"] = normalize_doi(r.get("doi")) or doi
    study["pmid"] = normalize_pmid(r.get("pmid")) or pmid
    study["title"] = _strip_tags(r.get("title"))
    study["journal"] = normalize_ws(r.get("journalTitle") or "") or None
    study["year"] = _year_of(r.get("pubYear"))
    study["abstract"] = _strip_tags(r.get("abstractText"))
    author_string = r.get("authorString") or ""
    authors = [normalize_ws(a).split(" ")[0] for a in author_string.split(",") if a.strip()]
    study["authors"] = [a for a in authors if a]
    study["first_author"] = study["authors"][0] if study["authors"] else None
    pub_types = ((r.get("pubTypeList") or {}).get("pubType")) or []
    study["publication_types"] = [p for p in pub_types if isinstance(p, str)]
    study["is_preprint"] = (r.get("source") == "PPR"
                            or any(v in (study["journal"] or "").lower() for v in _PREPRINT_VENUES))
    study["url"] = f"https://europepmc.org/article/{r.get('source', 'MED')}/{r.get('id')}" if r.get("id") else None
    study["resolver"] = "europepmc"
    return study


# --- matching + orchestration -------------------------------------------

_JOURNAL_FILLER = frozenset({"of", "the", "and", "for", "in"})


def _initials(name):
    words = [w for w in _TOKEN_RE.findall((name or "").lower()) if w not in _JOURNAL_FILLER]
    return "".join(w[0] for w in words)


def _journal_agrees(a, b):
    """Token overlap, or one name is the initialism of the other (NEJM vs
    New England Journal of Medicine; BMJ vs British Medical Journal)."""
    ta, tb = _tokens(a), _tokens(b)
    if ta & tb:
        return True
    ia, ib = _initials(a), _initials(b)
    wa = "".join(_TOKEN_RE.findall(a.lower()))
    wb = "".join(_TOKEN_RE.findall(b.lower()))
    return bool(ia and ib) and (wa == ib or wb == ia or wa == wb)

def plausible_match(identifiers, study):
    """Accept a candidate only when the article's own description of the
    study supports it: title overlap or a named author present, and no
    contradiction on journal or year. With nothing to check against, the
    answer is no — we never take a search engine's top hit on faith."""
    if not study:
        return False
    ids = identifiers or {}
    evidence = False
    title = ids.get("title")
    if isinstance(title, str) and title.strip():
        want = _tokens(title)
        have = _tokens(study.get("title"))
        if want and len(want & have) / len(want) >= 0.5:
            evidence = True
    author = ids.get("first_author")
    if isinstance(author, str) and author.strip():
        surname = normalize_ws(author).split(" ")[-1].lower()
        if surname and any(surname == (a or "").lower() for a in study.get("authors") or []):
            evidence = True
    if not evidence:
        return False
    journal = ids.get("journal")
    if isinstance(journal, str) and journal.strip() and study.get("journal"):
        if not _journal_agrees(journal, study["journal"]):
            return False
    year = _year_of(ids.get("year"))
    if year and study.get("year") and abs(year - study["year"]) > 1:
        return False
    return True


def _merge_abstract(study, other):
    """Copy the abstract (and any missing ids) from a second lookup."""
    if not other:
        return study
    if not study.get("abstract") and other.get("abstract"):
        study["abstract"] = other["abstract"]
        study["resolver"] = f"{study['resolver']}+{other['resolver']}"
    for key in ("pmid", "doi", "journal", "year", "first_author"):
        if not study.get(key) and other.get(key):
            study[key] = other[key]
    if not study.get("authors") and other.get("authors"):
        study["authors"] = other["authors"]
    if not study.get("publication_types") and other.get("publication_types"):
        study["publication_types"] = other["publication_types"]
    study["is_preprint"] = bool(study.get("is_preprint") or other.get("is_preprint"))
    return study


def _fill_abstract(study, *, session, contact_email):
    if study.get("abstract"):
        return study
    other = europepmc_lookup(doi=study.get("doi"), pmid=study.get("pmid"),
                             session=session, contact_email=contact_email)
    study = _merge_abstract(study, other)
    if study.get("abstract"):
        return study
    pmid = study.get("pmid")
    if not pmid and study.get("doi"):
        ids = pubmed_search(f"{study['doi']}[AID]", session=session, contact_email=contact_email)
        pmid = ids[0] if ids else None
    if pmid:
        study = _merge_abstract(study, pubmed_fetch(pmid, session=session, contact_email=contact_email))
    return study


def resolve_study(identifiers, *, session=None, contact_email=""):
    """identifiers: {doi, pmid, title, first_author, journal, year, ...}
    (any subset, values may be None). Returns a study dict or None."""
    ids = identifiers or {}
    kw = {"session": session, "contact_email": contact_email}

    doi = normalize_doi(ids.get("doi"))
    if doi:
        study = crossref_work(doi, **kw)
        if not study:
            study = europepmc_lookup(doi=doi, **kw)
        if study:
            return _fill_abstract(study, **kw)

    pmid = normalize_pmid(ids.get("pmid"))
    if pmid:
        study = pubmed_fetch(pmid, **kw)
        if study:
            return _fill_abstract(study, **kw)

    study = crossref_search(ids, **kw)
    if study:
        return _fill_abstract(study, **kw)

    term = pubmed_term(ids)
    if term:
        for candidate in pubmed_search(term, **kw)[:MAX_CANDIDATES]:
            study = pubmed_fetch(candidate, **kw)
            if study and plausible_match(ids, study):
                return _fill_abstract(study, **kw)
    return None
