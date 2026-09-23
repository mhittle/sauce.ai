"""Literature search: PubMed (E-utilities) and Europe PMC (abstracts,
open-access full text, cited-by counts, and the citation graph for one-hop
snowballing).

Both APIs are free and keyless. HTTP goes through one injectable
``http_get(url, params) -> str`` so tests run without the network, and
through an optional cache (the store's http_cache table).
"""
from __future__ import annotations

import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Callable, Protocol
from urllib.parse import urlparse

import requests

from .config import Settings
from .schema import Study

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"

HttpGet = Callable[[str, dict], str]

METHOD_TERMS = ['algorithm*', '"case definition*"', '"case-finding"', 'phenotyp*', '"case ascertainment"',
                '"case identification"', '"identifying cases"', '"coding algorithm*"']
VALIDATION_TERMS = ['validat*', '"positive predictive value"', 'sensitivity', 'specificity', 'accuracy']
DATA_TERMS = ['"administrative data"', '"administrative health"', 'claims', '"electronic health record*"',
              '"electronic medical record*"', '"health records"', '"International Classification of Diseases"',
              'ICD', 'billing', '"health care database*"', '"routinely collected"', 'registry']
MESH_DATA = ['"Electronic Health Records"[MeSH Terms]', '"Administrative Claims, Healthcare"[MeSH Terms]',
             '"International Classification of Diseases"[MeSH Terms]']
RELEVANT_TITLE = re.compile(r"validat|algorithm|case definition|case[- ]finding|identif|accuracy|"
                            r"predictive value|phenotyp|ascertain", re.I)


class Cache(Protocol):
    def cache_get(self, key: str, ttl_s: int) -> str | None: ...
    def cache_put(self, key: str, body: str) -> None: ...


class _HostLimiter:
    def __init__(self) -> None:
        self.last: dict[str, float] = {}
        self.lock = threading.Lock()

    def wait(self, host: str, gap: float) -> None:
        with self.lock:
            now = time.monotonic()
            t = max(now, self.last.get(host, 0.0) + gap)
            self.last[host] = t
        if t > now:
            time.sleep(t - now)


def requests_get(url: str, params: dict) -> str:
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=45,
                             headers={"User-Agent": "sauce.ai-phenotype/1.0 (mailto:phenotype@sauce.ai)"})
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            last = RuntimeError(f"HTTP {r.status_code} from {urlparse(url).netloc}")
            try:
                if float(r.headers.get("Retry-After", 0)) > 60:
                    break   # a quota, not a blip: don't hold the job hostage
            except ValueError:
                pass
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return ""
        r.raise_for_status()
        return r.text
    raise RuntimeError(f"literature fetch failed: {last}")


def _tiab(terms: list[str]) -> str:
    return "(" + " OR ".join(f"{t}[tiab]" for t in terms) + ")"


def pubmed_query(condition: str, synonyms: list[str] | None = None) -> str:
    names = [condition, *(synonyms or [])]
    cond = "(" + " OR ".join(f'"{n}"[tiab] OR "{n}"[MeSH Terms]' for n in names if n) + ")"
    data = "(" + _tiab(DATA_TERMS)[1:-1] + " OR " + " OR ".join(MESH_DATA) + ")"
    return f"{cond} AND {_tiab(METHOD_TERMS)} AND {_tiab(VALIDATION_TERMS)} AND {data}"


def europepmc_query(condition: str, synonyms: list[str] | None = None) -> str:
    names = " OR ".join(f'"{n}"' for n in [condition, *(synonyms or [])] if n)
    strip = lambda ts: " OR ".join(t.replace("*", "") for t in ts)
    return (f"({names}) AND ({strip(METHOD_TERMS)}) AND ({strip(VALIDATION_TERMS)}) "
            f"AND ({strip(DATA_TERMS)}) AND SRC:MED")


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def study_key(pmid: str = "", doi: str = "", title: str = "") -> str:
    if pmid:
        return f"pmid:{pmid}"
    if doi:
        return f"doi:{doi.lower()}"
    return "t:" + norm_title(title)[:120]


def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def parse_pubmed_xml(xml: str) -> list[Study]:
    out = []
    if not xml.strip():
        return out
    root = ET.fromstring(xml)
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        pmid = _text(mc.find("PMID")) if mc is not None else ""
        a = mc.find("Article") if mc is not None else None
        if a is None or not pmid:
            continue
        parts = []
        for t in a.findall("Abstract/AbstractText"):
            lab = t.get("Label")
            parts.append(f"{lab}: {_text(t)}" if lab else _text(t))
        authors = []
        for au in a.findall("AuthorList/Author"):
            ln, ini = _text(au.find("LastName")), _text(au.find("Initials"))
            if ln:
                authors.append(f"{ln} {ini}".strip())
            elif au.find("CollectiveName") is not None:
                authors.append(_text(au.find("CollectiveName")))
        year = _text(a.find("Journal/JournalIssue/PubDate/Year")) or \
            _text(a.find("Journal/JournalIssue/PubDate/MedlineDate"))[:4]
        ids = {i.get("IdType"): _text(i) for i in art.findall("PubmedData/ArticleIdList/ArticleId")}
        out.append(Study(key=study_key(pmid), title=_text(a.find("ArticleTitle")), authors=", ".join(authors),
                         journal=_text(a.find("Journal/ISOAbbreviation")) or _text(a.find("Journal/Title")),
                         year=int(year) if year.isdigit() else None, pmid=pmid, pmcid=ids.get("pmc", ""),
                         doi=ids.get("doi", ""), abstract="\n".join(parts)))
    return out


def parse_europepmc_json(body: str) -> tuple[list[Study], dict[str, bool]]:
    """Studies plus {pmcid: is_open_access}."""
    if not body.strip():
        return [], {}
    data = json.loads(body)
    out, oa = [], {}
    for r in (data.get("resultList") or {}).get("result") or []:
        pmid, doi, pmcid = r.get("pmid", ""), r.get("doi", ""), r.get("pmcid", "")
        journal = ((r.get("journalInfo") or {}).get("journal") or {}).get("isoabbreviation") or \
            r.get("journalTitle", "")
        yr = str(r.get("pubYear", ""))
        out.append(Study(key=study_key(pmid, doi, r.get("title", "")), title=(r.get("title") or "").strip(),
                         authors=(r.get("authorString") or "").rstrip("."), journal=journal,
                         year=int(yr) if yr.isdigit() else None, pmid=pmid, pmcid=pmcid, doi=doi,
                         abstract=re.sub(r"<[^>]+>", " ", r.get("abstractText") or "").strip(),
                         cited_by=r.get("citedByCount")))
        if pmcid:
            oa[pmcid] = r.get("isOpenAccess") == "Y"
    return out, oa


def fulltext_from_jats(xml: str, limit: int = 150_000) -> str:
    """Body text + tables from a JATS document (where the numbers usually are)."""
    if not xml.strip():
        return ""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ""
    chunks = []
    body = root.find("body")
    if body is not None:
        for el in body:
            t = _text(el)
            title = _text(el.find("title")) if el.tag == "sec" else ""
            if re.search(r"acknowledg|funding|conflict|disclos", title, re.I):
                continue
            chunks.append(t)
    for tw in root.iter("table-wrap"):
        cap = _text(tw.find("caption"))
        rows = [" | ".join(_text(c) for c in tr) for tr in tw.iter("tr")]
        chunks.append(f"[TABLE] {cap}\n" + "\n".join(rows))
    text = "\n\n".join(c for c in chunks if c)
    return text[:limit]


class Literature:
    def __init__(self, settings: Settings, http_get: HttpGet | None = None, cache: Cache | None = None) -> None:
        self.settings = settings
        self.http_get = http_get or requests_get
        self.cache = cache
        self.limiter = _HostLimiter()
        self.calls = 0

    def _get(self, url: str, params: dict) -> str:
        key = url + "?" + json.dumps(params, sort_keys=True)
        if self.cache:
            hit = self.cache.cache_get(key, self.settings.http_cache_ttl_s)
            if hit is not None:
                return hit
        host = urlparse(url).netloc
        gap = (0.11 if self.settings.ncbi_api_key else 0.35) if "ncbi" in host else 0.12
        self.limiter.wait(host, gap)
        self.calls += 1
        body = self.http_get(url, params)
        if self.cache and body:
            self.cache.cache_put(key, body)
        return body

    def _eutils_params(self, **kw) -> dict:
        p = {"tool": "sauce.ai-phenotype", "email": self.settings.contact_email, **kw}
        if self.settings.ncbi_api_key:
            p["api_key"] = self.settings.ncbi_api_key
        return p

    # -- PubMed ---------------------------------------------------------------
    def pubmed_search(self, term: str, retmax: int = 200) -> list[str]:
        body = self._get(f"{EUTILS}/esearch.fcgi", self._eutils_params(
            db="pubmed", term=term, retmax=retmax, retmode="json", sort="relevance"))
        if not body:
            return []
        return list((json.loads(body).get("esearchresult") or {}).get("idlist") or [])

    def pubmed_fetch(self, pmids: list[str]) -> list[Study]:
        out = []
        for i in range(0, len(pmids), 100):
            chunk = pmids[i:i + 100]
            out += parse_pubmed_xml(self._get(f"{EUTILS}/efetch.fcgi", self._eutils_params(
                db="pubmed", id=",".join(chunk), retmode="xml")))
        return out

    def find_title(self, title: str) -> Study | None:
        """Resolve a known title to a real PubMed record (never trust a model's citation)."""
        words = [w for w in norm_title(title).split() if len(w) > 3][:12]
        if not words:
            return None
        ids = self.pubmed_search(" AND ".join(f"{w}[ti]" for w in words), retmax=5)
        want = set(words)
        for s in self.pubmed_fetch(ids):
            have = set(norm_title(s.title).split())
            if len(want & have) >= 0.8 * len(want):
                return s
        return None

    # -- Europe PMC -------------------------------------------------------------
    def europepmc_search(self, query: str, page_size: int = 100) -> tuple[list[Study], dict[str, bool]]:
        body = self._get(f"{EPMC}/search", {"query": query, "format": "json", "resultType": "core",
                                            "pageSize": min(1000, page_size)})
        return parse_europepmc_json(body)

    def fulltext(self, pmcid: str) -> str:
        return fulltext_from_jats(self._get(f"{EPMC}/{pmcid}/fullTextXML", {}))

    # -- citation graph (Europe PMC) ---------------------------------------------
    def _links(self, pmid: str, kind: str) -> tuple[list[dict], int]:
        body = self._get(f"{EPMC}/MED/{pmid}/{kind}", {"format": "json", "pageSize": 200})
        if not body:
            return [], 0
        data = json.loads(body)
        lst = (data.get("citationList") or {}).get("citation") if kind == "citations" else \
            (data.get("referenceList") or {}).get("reference")
        return list(lst or []), int(data.get("hitCount") or 0)

    def snowball(self, s: Study, limit: int = 40) -> list[str]:
        """PMIDs of relevant-looking papers citing or cited by ``s``; also
        fills ``s.cited_by`` when missing."""
        if not s.pmid:
            return []
        citing, hits = self._links(s.pmid, "citations")
        if s.cited_by is None:
            s.cited_by = hits
        refs, _ = self._links(s.pmid, "references")
        pmids: list[str] = []
        for r in citing + refs:
            pm = str(r.get("id") or "")
            if r.get("source") == "MED" and pm.isdigit() and RELEVANT_TITLE.search(r.get("title") or "") \
                    and pm not in pmids:
                pmids.append(pm)
        return pmids[:limit]


def merge(into: dict[str, Study], studies: list[Study]) -> int:
    """Deduplicate by PMID, then DOI, then normalized title. Returns # new."""
    by_doi = {s.doi.lower(): k for k, s in into.items() if s.doi}
    by_title = {norm_title(s.title): k for k, s in into.items()}
    new = 0
    for s in studies:
        k = s.key if s.key in into else by_doi.get(s.doi.lower()) if s.doi else None
        k = k or by_title.get(norm_title(s.title))
        if k and k in into:
            cur = into[k]
            for f in ("pmid", "pmcid", "doi", "abstract", "journal", "authors", "cited_by"):
                if getattr(cur, f) in ("", None) and getattr(s, f) not in ("", None):
                    setattr(cur, f, getattr(s, f))
            continue
        into[s.key] = s
        if s.doi:
            by_doi[s.doi.lower()] = s.key
        by_title[norm_title(s.title)] = s.key
        new += 1
    return new
