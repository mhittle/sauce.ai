"""Server-rendered, indexable pages for search engines.

The app at / is a single-page app whose views live behind hash routes, which
search engines don't treat as pages. This module adds plain HTML pages,
complete in the first response, built from the same store the API uses:

- /datasets/                 hub: every condition page + datasets, 100 per page
- /datasets/<slug>-<id>      one dataset (wrong slug -> 301 to the canonical URL)
- /conditions/               hub: every condition with datasets
- /conditions/<slug>         one condition: dataset count + FDA activity, datasets
- /robots.txt, /sitemap.xml

Pages carry a canonical link and JSON-LD (schema.org Dataset on dataset
pages, ItemList on lists). Fields the catalog doesn't have are left out,
never filled in. Nothing here changes the SPA, the API or /files/.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import unicodedata
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from .devices import fda_database_url
from .store import Store, normalize_condition

PUBLIC_URL = os.environ.get("DATASETS_PUBLIC_URL",
                            "https://datasets.paloaltohealthlabs.com").rstrip("/")
SITE = "Palo Alto Health Labs"
PER_PAGE = 100
ROBOTS = (
    "User-agent: *\n"
    "Allow: /\n"
    "Disallow: /api/\n"
    "Disallow: /files/\n"
    "\n"
    f"Sitemap: {PUBLIC_URL}/sitemap.xml\n"
)
# Ownership/key files for search engines, served byte-for-byte as issued.
BING_SITE_AUTH = ('<?xml version="1.0"?>\n<users>\n\t<user>EB4E3F5B02489117E4B4979A488800DF'
                  "</user>\n</users>")
INDEXNOW_KEY = "4e7cb8cfba444e299c57c0d936696e24"
ACCESS_TEXT = {"open": "Open access", "credentialed": "Credentialed access",
               "dua": "Data use agreement", "request": "On request", "commercial": "Commercial",
               "restricted": "Restricted", "unknown": "Access unknown"}


def slugify(text: str) -> str:
    """Lowercase, ASCII-folded, non-alphanumerics to '-', no repeats or
    trailing dashes, at most 80 characters."""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80].strip("-")


def dataset_path(d: dict) -> str:
    s = slugify(d.get("title") or "")
    return f"/datasets/{s}-{d['id']}" if s else f"/datasets/{d['id']}"


def condition_path(slug: str) -> str:
    return f"/conditions/{slug}"


def e(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def access_text(a: str | None) -> str:
    return ACCESS_TEXT.get(a or "unknown", (a or "unknown").replace("_", " ").capitalize())


def jsonld(obj: dict) -> str:
    # "</" can't appear inside a script element.
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:.")
    return cut + "…"


class Catalog:
    """Conditions with datasets, keyed by URL slug (cached briefly: the
    ranked query is the expensive one)."""

    TTL = 300

    def __init__(self, store: Store):
        self.store = store
        self._lock = threading.Lock()
        self._at = 0.0
        self._by_slug: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}
        self._sitemap: tuple[float, bytes] | None = None

    def conditions(self) -> tuple[dict[str, dict], dict[str, dict]]:
        with self._lock:
            if time.time() - self._at > self.TTL:
                by_slug, by_name = {}, {}
                rows = sorted(self.store.conditions_ranked(only_with_datasets=True),
                              key=lambda c: (c["display"] or c["name"]).lower())
                for c in rows:
                    base = slugify(c["display"] or c["name"]) or slugify(c["name"]) or "condition"
                    slug, n = base, 2
                    while slug in by_slug:          # never two conditions on one URL
                        slug, n = f"{base}-{n}", n + 1
                    c = {**c, "slug": slug}
                    by_slug[slug] = c
                    by_name[c["name"]] = c
                self._by_slug, self._by_name, self._at = by_slug, by_name, time.time()
            return self._by_slug, self._by_name

    def sitemap(self, build) -> bytes:
        with self._lock:
            if self._sitemap and time.time() - self._sitemap[0] < self.TTL:
                return self._sitemap[1]
        body = build()
        with self._lock:
            self._sitemap = (time.time(), body)
        return body


# ---------------------------------------------------------------- page shell
# Google Analytics: the same property and booking-click event as paloaltohealthlabs.com,
# on every page this app serves (index.html gets it from app/main.py).
GTAG = """<!-- Google tag (gtag.js), same property as paloaltohealthlabs.com -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-WHDQHLHXJ4"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-WHDQHLHXJ4');
  // Conversion: any click on the booking link, with the page it happened on.
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest && e.target.closest('a[href*="calendar.app.google"]');
    if (a) gtag('event', 'book_call_click', { page_path: location.pathname, link_text: (a.textContent || '').trim().slice(0, 60) });
  });
</script>"""

# Shared site header: a copy of paloaltohealthlabs.com's menu (generated there by
# .github/scripts/apply_site_nav.py; keep the two in step). Links are absolute
# because this app runs on a subdomain; styles and behaviour load from the main site.
SITE_NAV_CSS = '<link rel="stylesheet" href="https://paloaltohealthlabs.com/assets/css/site-nav.css?v=20261119b">'
SITE_NAV_JS = '<script src="https://paloaltohealthlabs.com/assets/js/site-nav.js?v=20261119b" defer></script>'
SITE_NAV = """<header class="pn" id="site-nav">
  <div class="pn-in">
    <a class="pn-brand" href="https://paloaltohealthlabs.com/" aria-label="Palo Alto Health Labs home"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 13 H6 L8 8 L11 17 L14 10 L16 13 H22" fill="none" stroke="#2433D9" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>Palo Alto Health Labs</a>
    <button class="pn-toggle" type="button" aria-expanded="false" aria-controls="pn-links" hidden>Menu</button>
    <nav class="pn-links" id="pn-links" aria-label="Site">
      <a class="pn-l" href="https://paloaltohealthlabs.com/fabrica/">Fabrica</a>
      <a class="pn-l" href="https://paloaltohealthlabs.com/co-scientist/">Co-Scientist</a>
      <a class="pn-l pn-cur" aria-current="true" href="/">Datasets</a>
      <a class="pn-l" href="https://thebrief.paloaltohealthlabs.com">The Brief</a>
      <div class="pn-dd">
        <button class="pn-l pn-dd-t" type="button" aria-expanded="false" aria-controls="pn-panel">Services<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 4.2l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
        <div class="pn-panel" id="pn-panel">
          <div class="pn-col"><span class="pn-h">Services</span><a href="https://paloaltohealthlabs.com/fractional-cto/">Fractional CTO</a><a href="https://paloaltohealthlabs.com/services/vibe-coded-app-to-hipaa/">Vibe-coded app to HIPAA-ready</a><a href="https://paloaltohealthlabs.com/services/clinical-ai-assessment.html">Clinical AI assessment</a><a href="https://paloaltohealthlabs.com/services/expert-clinical-labeling.html">Expert data labeling</a><a href="https://paloaltohealthlabs.com/#services">All services</a></div>
          <div class="pn-col"><span class="pn-h">Guides and resources</span><a href="https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/">HIPAA guide for vibe-coded apps</a><a href="https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/2026-baa-matrix/">2026 BAA matrix</a><a href="https://paloaltohealthlabs.com/guides/vibe-coded-hipaa/stack-checker/">Stack Checker</a><a href="https://paloaltohealthlabs.com/resources/">Resource hub</a><a href="https://paloaltohealthlabs.com/resources/downloads/">Downloads</a><a href="https://paloaltohealthlabs.com/blog/">Blog</a></div>
          <div class="pn-foot"><a href="https://paloaltohealthlabs.com/about.html">About</a><a href="https://calendar.app.google/eJZVyYnoFJD67mGX9" target="_blank" rel="noopener">Book a free call</a></div>
        </div>
      </div>
    </nav>
  </div>
</header>"""


STYLE = """
.seo { max-width: 960px; margin: 0 auto; padding: 28px var(--pad, 24px) 64px; }
.seo h1 { font-size: clamp(28px, 4vw, 40px); line-height: 1.12; letter-spacing: -.02em; margin: 6px 0 12px; }
.seo h2 { font-size: 20px; margin: 32px 0 10px; }
.seo .crumbs { font-size: 13px; color: var(--muted); }
.seo .crumbs a { color: var(--muted); }
.seo .lead { font-size: 17px; max-width: 75ch; }
.seo table.facts { margin-top: 18px; border-collapse: collapse; width: 100%; max-width: 760px; font-size: 14px; }
.seo table.facts th { text-align: left; width: 170px; color: var(--muted); font-weight: 500; vertical-align: top; }
.seo table.facts th, .seo table.facts td { padding: 7px 10px 7px 0; border-bottom: 1px solid var(--line); }
.seo .steps { white-space: pre-wrap; background: var(--chip); padding: 12px 14px; font-size: 14px; max-width: 80ch; }
.seo ul.links { padding-left: 18px; }
.seo ul.links li { margin: 4px 0; }
.seo .meta { color: var(--muted); font-size: 13px; }
.seo .stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 6px; }
.seo .stat { border: 1px solid var(--line); padding: 10px 14px; min-width: 130px; }
.seo .stat b { display: block; font-size: 26px; letter-spacing: -.02em; }
.seo .stat span { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.seo .cols { columns: 3 220px; column-gap: 24px; font-size: 14px; }
.seo .cols a { display: block; margin: 3px 0; break-inside: avoid; }
.seo .pager { display: flex; gap: 12px; align-items: center; margin-top: 18px; font-size: 14px; }
.seo-nav { border-bottom: 1px solid var(--line); background: #fafafa; }
.seo-nav .wrap { display: flex; gap: 24px; align-items: center; height: 44px; font-size: 14px;
                 max-width: 1600px; padding: 0 clamp(20px, 5vw, 80px); }  /* same box as the site menu */
.seo-nav a { text-decoration: none; font-weight: 500; color: var(--muted); }
.seo-nav a:hover { color: var(--ink); }
"""


def page(*, title: str, description: str, path: str, body: str, ld: list[dict] | None = None,
         asset_v: str = "", noindex: bool = False, status: int = 200) -> HTMLResponse:
    canonical = PUBLIC_URL + path if status == 200 else None
    ld_html = "".join(f'<script type="application/ld+json">{jsonld(o)}</script>\n' for o in ld or [])
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{GTAG}
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
{f'<link rel="canonical" href="{e(canonical)}">' if canonical else ''}
{robots}<meta property="og:type" content="website">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
{f'<meta property="og:url" content="{e(canonical)}">' if canonical else ''}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css{('?v=' + asset_v) if asset_v else ''}">
{SITE_NAV_CSS}
<style>{STYLE}</style>
{ld_html}</head>
<body>
{SITE_NAV}
<nav class="seo-nav" aria-label="Catalog"><div class="wrap">
<a href="/">Search</a>
<a href="/datasets/">All datasets</a>
<a href="/conditions/">Conditions</a>
</div></nav>
<main class="seo">
{body}
</main>
{SITE_NAV_JS}
</body>
</html>"""
    return HTMLResponse(doc, status_code=status)


def not_found(asset_v: str, what: str = "page") -> HTMLResponse:
    return page(title=f"Not found | {SITE}", description=f"This {what} isn't in the catalog.",
                path="/404", asset_v=asset_v, noindex=True, status=404,
                body=f"<h1>Not found</h1><p>This {e(what)} isn't in the catalog. "
                     f'Browse <a href="/datasets/">all datasets</a> or '
                     f'<a href="/conditions/">conditions</a>.</p>')


def item_list(name: str, path: str, items: list[tuple[str, str]]) -> dict:
    return {"@context": "https://schema.org", "@type": "ItemList", "name": name,
            "url": PUBLIC_URL + path, "numberOfItems": len(items),
            "itemListElement": [{"@type": "ListItem", "position": i, "url": PUBLIC_URL + p,
                                 "name": n} for i, (n, p) in enumerate(items, 1)]}


# ---------------------------------------------------------------- dataset
def dataset_jsonld(d: dict, path: str) -> dict:
    desc = re.sub(r"\s+", " ", d.get("description") or "").strip()
    if len(desc) < 50:
        # Google requires 50+ characters; build it only from catalog facts.
        bits = [d["title"]]
        if d.get("source"):
            bits.append(f"a dataset from {d['source']}")
        if d.get("conditions"):
            bits.append("covering " + ", ".join(d["conditions"][:5]))
        if d.get("modalities"):
            bits.append("data: " + ", ".join(d["modalities"][:5]))
        bits.append(access_text(d.get("access_type")).lower())
        desc = (desc + " " if desc else "") + "; ".join(bits) + "."
    out: dict[str, Any] = {"@context": "https://schema.org", "@type": "Dataset",
                           "name": d["title"], "description": desc[:5000],
                           "url": PUBLIC_URL + path}
    if d.get("url"):
        out["sameAs"] = d["url"]
    lic = (d.get("license") or "").strip()
    if lic:
        out["license"] = lic if re.match(r"https?://", lic) else {"@type": "CreativeWork", "name": lic}
    if d.get("source"):
        out["creator"] = {"@type": "Organization", "name": d["source"]}
    if d.get("access_type") == "open":
        out["isAccessibleForFree"] = True
    kw = [*(d.get("conditions") or []), *(d.get("modalities") or []), *(d.get("tags") or [])]
    if kw:
        out["keywords"] = list(dict.fromkeys(str(k) for k in kw))[:20]
    if d.get("citation"):
        out["citation"] = d["citation"]
    dl = [u for u in d.get("download_urls") or [] if re.match(r"https?://", u or "")]
    if dl:
        out["distribution"] = [{"@type": "DataDownload", "contentUrl": u} for u in dl[:20]]
    return out


def render_dataset(store: Store, cat: Catalog, d: dict, path: str, asset_v: str) -> HTMLResponse:
    _, by_name = cat.conditions()
    conds = [by_name.get(normalize_condition(c)) for c in d.get("conditions") or []]
    conds = [c for c in conds if c]
    access = access_text(d.get("access_type"))
    desc = (d.get("description") or "").strip()
    meta = clip(desc, 140) if desc else f"{d['title']}, from {d.get('source') or 'the catalog'}."
    meta = f"{meta} {access}."
    prof = d.get("profile") or {}
    dtype = prof.get("modality") or ", ".join(d.get("modalities") or [])
    formats = ", ".join(dict.fromkeys([*(d.get("file_formats") or []), *(prof.get("formats") or [])]))
    rows = [
        ("Source", e(d.get("source"))),
        ("Access", e(access)),
        ("Conditions", ", ".join(f'<a href="{condition_path(c["slug"])}">{e(c["display"])}</a>'
                                 for c in conds) or e(", ".join(d.get("conditions") or []))),
        ("Data type", e(dtype)),
        ("Format", e(formats)),
        ("Size", e(d.get("size"))),
        ("Subjects", e(d.get("n_subjects"))),
        ("Labels", e(d.get("labels"))),
        ("License", e(d.get("license"))),
        ("Citation", e(d.get("citation"))),
    ]
    facts = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows if v)
    src = (f'<p><a href="{e(d["url"])}" rel="noopener" target="_blank">Go to the source page '
           f'({e(d.get("source") or d["url"])}) →</a></p>') if d.get("url") else ""
    steps = (f'<div class="steps">{e(d["access_instructions"])}</div>'
             if d.get("access_instructions") else "<p>See the source page for access steps.</p>")
    dls = [u for u in d.get("download_urls") or [] if re.match(r"https?://", u or "")]
    dl_html = ("<p>Direct downloads:</p><ul class=\"links\">" + "".join(
        f'<li><a href="{e(u)}" rel="noopener nofollow">{e(u.rsplit("/", 1)[-1] or u)}</a></li>'
        for u in dls[:20]) + "</ul>") if dls else ""

    arts = store.dataset_articles(d["id"], limit=10)
    n_papers = d.get("n_articles") or 0
    paper_items = []
    for a in arts["items"]:
        href = a.get("url") or (f"https://doi.org/{a['doi']}" if a.get("doi") else None) or \
            (f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/" if a.get("pmid") else None)
        label = e(a.get("title"))
        tail = " · ".join(e(x) for x in (a.get("venue"), a.get("year")) if x)
        tag = " (dataset paper)" if a.get("is_descriptor") else ""
        link = f'<a href="{e(href)}" rel="noopener">{label}</a>' if href else label
        extra = f' <span class="meta">{tail}</span>' if tail else ""
        paper_items.append(f"<li>{link}{tag}{extra}</li>")
    papers_html = (f"<p><b>{n_papers:,}</b> papers use or cite this dataset"
                   + (". Most cited:" if paper_items else ".") + "</p>"
                   + (f'<ul class="links">{"".join(paper_items)}</ul>' if paper_items else "")
                   + f'<p class="meta"><a href="/#/dataset/{quote(d["id"])}">All papers in the '
                     f"interactive catalog</a></p>")

    comp = store.compatible(d["id"], 25)
    comp_html = (f"<p><b>{len(comp)}</b> datasets could be combined with this one or used to "
                 "validate a model trained on it:</p><ul class=\"links\">" + "".join(
                     f'<li><a href="{dataset_path(c)}">{e(c["title"])}</a>'
                     f'<span class="meta"> · {e(c.get("source") or "")} · {e(access_text(c.get("access_type")))}</span></li>'
                     for c in comp) + "</ul>") if comp else "<p>No compatible datasets identified yet.</p>"

    devs = d.get("devices") or []
    dev_html = (f"<p><b>{len(devs)}</b> FDA submissions reference this dataset:</p><ul class=\"links\">"
                + "".join(f'<li><a href="{e(fda_database_url(v["k_number"]))}" rel="noopener">'
                          f'{e(v["k_number"])}</a> {e(v.get("device_name"))}'
                          f'<span class="meta"> · {e(v.get("applicant"))} · {e(v.get("decision_date"))}</span></li>'
                          for v in devs[:50]) + "</ul>") if devs else \
        "<p>No FDA submissions linked to this dataset yet.</p>"
    cond_html = ("<ul class=\"links\">" + "".join(
        f'<li><a href="{condition_path(c["slug"])}">{e(c["display"])} datasets</a>'
        f'<span class="meta"> · {c["n_datasets"]} datasets · {c["fda_510k_count"] or 0} FDA 510(k)</span></li>'
        for c in conds) + "</ul>") if conds else ""

    crumb = (f' › <a href="{condition_path(conds[0]["slug"])}">{e(conds[0]["display"])}</a>'
             if conds else "")
    body = f"""<p class="crumbs"><a href="/datasets/">Datasets</a>{crumb}</p>
<h1>{e(d["title"])}</h1>
{f'<p class="lead">{e(desc)}</p>' if desc else ''}
<table class="facts">{facts}</table>
<h2>How to access</h2>
{steps}
{src}{dl_html}
<h2>Papers using this dataset</h2>
{papers_html}
<h2>Compatible datasets</h2>
{comp_html}
<h2>FDA submissions</h2>
{dev_html}
{('<h2>Conditions</h2>' + cond_html) if cond_html else ''}
<p class="meta"><a href="/#/dataset/{quote(d['id'])}">Open in the interactive catalog</a></p>"""
    return page(title=f"{d['title']} dataset — access, papers & FDA submissions | {SITE}",
                description=clip(meta, 200), path=path, body=body, asset_v=asset_v,
                ld=[dataset_jsonld(d, path)], noindex=d.get("kind") == "repository")


# ---------------------------------------------------------------- condition
def render_condition(store: Store, c: dict, asset_v: str) -> HTMLResponse:
    path = condition_path(c["slug"])
    name = c["display"] or c["name"]
    items = store.browse_datasets(condition=c["name"], sort="papers", limit=5000)["items"]
    n, n_open = c["n_datasets"], c["n_open"]
    k510, dn = c["fda_510k_count"] or 0, c["fda_denovo_count"] or 0
    intro = (f"<b>{n:,}</b> {'dataset' if n == 1 else 'datasets'} for {e(name)} "
             f"(<b>{n_open:,}</b> open access), alongside <b>{k510:,}</b> FDA 510(k) "
             f"{'clearance' if k510 == 1 else 'clearances'} and <b>{dn:,}</b> De Novo "
             f"{'authorization' if dn == 1 else 'authorizations'} for devices in this area.")
    stats = "".join(f'<div class="stat"><b>{v:,}</b><span>{k}</span></div>' for k, v in (
        ("Datasets", n), ("Open access", n_open), ("FDA 510(k)", k510), ("De Novo", dn)))
    syn = [s for s in json.loads(c.get("synonyms") or "[]") if s] if isinstance(c.get("synonyms"), str) \
        else [s for s in c.get("synonyms") or [] if s]
    def row(d: dict) -> str:
        bits = [e(d.get("source") or ""), e(access_text(d.get("access_type"))),
                f'{d["n_articles"]:,} papers']
        if d.get("n_devices"):
            bits.append(f'{d["n_devices"]} FDA submissions')
        return (f'<li><a href="{dataset_path(d)}">{e(d["title"])}</a>'
                f'<span class="meta"> · {" · ".join(b for b in bits if b)}</span></li>')
    rows = "".join(row(d) for d in items)
    body = f"""<p class="crumbs"><a href="/conditions/">Conditions</a></p>
<h1>{e(name)} datasets</h1>
<p class="lead">{intro}</p>
<div class="stats">{stats}</div>
{f'<p class="meta">Also known as: {e(", ".join(syn[:12]))}</p>' if syn else ''}
<h2>Datasets, most-used first</h2>
<ul class="links">{rows}</ul>
<p class="meta"><a href="/#/datasets?condition={quote(c['name'])}">Open {e(name)} in the interactive catalog</a>
(FDA submissions, papers and filters)</p>"""
    desc = (f"{n} {name} datasets ({n_open} open access) with access steps and the papers that "
            f"use them, plus {k510} FDA 510(k) and {dn} De Novo submissions.")
    return page(title=f"{name} datasets — open data, papers & FDA clearances | {SITE}",
                description=desc, path=path, body=body, asset_v=asset_v,
                ld=[item_list(f"{name} datasets", path, [(d["title"], dataset_path(d)) for d in items])])


# ---------------------------------------------------------------- routes
def register(app: FastAPI, store: Store, asset_v: str = "") -> Catalog:
    cat = Catalog(store)

    def all_datasets() -> list[dict]:
        with store._conn() as c:
            rows = c.execute(
                "SELECT d.id, d.title, d.last_seen, d.first_seen,"
                " (SELECT COUNT(*) FROM dataset_articles a WHERE a.dataset_id = d.id"
                "    AND a.is_descriptor = 0) AS n_articles"
                " FROM datasets d WHERE d.kind = 'dataset'"
                " ORDER BY n_articles DESC, d.title COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    @app.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
    def robots():
        return PlainTextResponse(ROBOTS)

    @app.api_route("/BingSiteAuth.xml", methods=["GET", "HEAD"], include_in_schema=False)
    def bing_site_auth():
        return Response(BING_SITE_AUTH, media_type="application/xml")

    @app.api_route(f"/{INDEXNOW_KEY}.txt", methods=["GET", "HEAD"], include_in_schema=False)
    def indexnow_key():
        return PlainTextResponse(INDEXNOW_KEY)

    @app.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
    def sitemap():
        def build() -> bytes:
            ds = all_datasets()
            _, by_name = cat.conditions()
            with store._conn() as c:
                cond_last = {r[0]: r[1] for r in c.execute(
                    "SELECT dc.condition, MAX(d.last_seen) FROM dataset_conditions dc"
                    " JOIN datasets d ON d.id = dc.dataset_id WHERE d.kind = 'dataset'"
                    " GROUP BY dc.condition")}
            newest = max((d["last_seen"] or "" for d in ds), default="")[:10]
            urls = [("/", newest), ("/datasets/", newest), ("/conditions/", newest)]
            urls += [(dataset_path(d), (d["last_seen"] or d["first_seen"] or "")[:10]) for d in ds]
            urls += [(condition_path(c["slug"]), (cond_last.get(name) or "")[:10])
                     for name, c in sorted(by_name.items(), key=lambda kv: kv[1]["slug"])]
            out = ['<?xml version="1.0" encoding="UTF-8"?>',
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
            for p, last in urls:
                out.append(f"<url><loc>{html.escape(PUBLIC_URL + p)}</loc>"
                           + (f"<lastmod>{last}</lastmod>" if last else "") + "</url>")
            out.append("</urlset>")
            return "\n".join(out).encode()
        return Response(cat.sitemap(build), media_type="application/xml")

    @app.api_route("/datasets", methods=["GET", "HEAD"], include_in_schema=False)
    def datasets_noslash():
        return RedirectResponse("/datasets/", status_code=301)

    @app.api_route("/conditions", methods=["GET", "HEAD"], include_in_schema=False)
    def conditions_noslash():
        return RedirectResponse("/conditions/", status_code=301)

    @app.api_route("/datasets/", methods=["GET", "HEAD"], include_in_schema=False)
    def datasets_hub(request: Request):
        try:
            pg = int(request.query_params.get("page", "1"))
        except ValueError:
            return not_found(asset_v)
        ds = all_datasets()
        pages = max(1, -(-len(ds) // PER_PAGE))
        if not 1 <= pg <= pages:
            return not_found(asset_v)
        chunk = ds[(pg - 1) * PER_PAGE: pg * PER_PAGE]
        by_slug, _ = cat.conditions()
        path = "/datasets/" if pg == 1 else f"/datasets/?page={pg}"
        conds = "".join(f'<a href="{condition_path(s)}">{e(c["display"])} <span class="meta">({c["n_datasets"]})</span></a>'
                        for s, c in by_slug.items())
        rows = "".join(f'<li><a href="{dataset_path(d)}">{e(d["title"])}</a>'
                       f'<span class="meta"> · {d["n_articles"]:,} papers</span></li>' for d in chunk)
        nav = []
        if pg > 1:
            nav.append(f'<a href="{"/datasets/" if pg == 2 else f"/datasets/?page={pg - 1}"}" rel="prev">← Previous</a>')
        nav.append(f"<span class=\"meta\">Page {pg} of {pages}</span>")
        if pg < pages:
            nav.append(f'<a href="/datasets/?page={pg + 1}" rel="next">Next →</a>')
        st = store.stats()
        body = f"""<h1>Datasets for medical AI</h1>
<p class="lead">{st['datasets']:,} medical datasets, each with how to get access, the papers that use it
and the FDA submissions behind its market. Browse by condition or the full list, most-used first.</p>
<h2>By condition</h2>
<div class="cols">{conds}</div>
<h2>All datasets{f' (page {pg})' if pg > 1 else ''}</h2>
<ol class="links" start="{(pg - 1) * PER_PAGE + 1}">{rows}</ol>
<nav class="pager">{''.join(nav)}</nav>"""
        return page(title=f"Datasets for medical AI{f' — page {pg}' if pg > 1 else ''} | {SITE}",
                    description=f"{st['datasets']:,} medical datasets for AI with access steps, "
                                f"papers and FDA submissions, organised by condition.",
                    path=path, body=body, asset_v=asset_v,
                    ld=[item_list("Datasets for medical AI", path,
                                  [(d["title"], dataset_path(d)) for d in chunk])])

    @app.api_route("/conditions/", methods=["GET", "HEAD"], include_in_schema=False)
    def conditions_hub():
        by_slug, _ = cat.conditions()
        rows = "".join(
            f'<li><a href="{condition_path(s)}">{e(c["display"])}</a><span class="meta"> · '
            f'{c["n_datasets"]} datasets · {c["n_open"]} open · {c["fda_510k_count"] or 0} FDA 510(k)'
            f' · {c["fda_denovo_count"] or 0} De Novo</span></li>' for s, c in by_slug.items())
        body = f"""<h1>Medical conditions — datasets &amp; FDA activity</h1>
<p class="lead">{len(by_slug)} conditions, each with the datasets available for it and the FDA 510(k)
and De Novo submissions for devices in the same area.</p>
<ul class="links">{rows}</ul>"""
        return page(title=f"Medical conditions — datasets & FDA activity | {SITE}",
                    description=f"{len(by_slug)} medical conditions with their datasets, open-access "
                                "counts, and FDA 510(k) and De Novo activity.",
                    path="/conditions/", body=body, asset_v=asset_v,
                    ld=[item_list("Medical conditions", "/conditions/",
                                  [(c["display"], condition_path(s)) for s, c in by_slug.items()])])

    @app.api_route("/datasets/{key}", methods=["GET", "HEAD"], include_in_schema=False)
    def dataset_page(key: str):
        ds_id = key.rsplit("-", 1)[-1]
        d = store.get_dataset(ds_id) if re.fullmatch(r"[A-Za-z0-9_]+", ds_id or "") else None
        if not d:
            return not_found(asset_v, "dataset")
        path = dataset_path(d)
        if f"/datasets/{key}" != path:
            return RedirectResponse(path, status_code=301)
        return render_dataset(store, cat, d, path, asset_v)

    @app.api_route("/conditions/{slug}", methods=["GET", "HEAD"], include_in_schema=False)
    def condition_page(slug: str):
        by_slug, _ = cat.conditions()
        c = by_slug.get(slug)
        if not c:
            return not_found(asset_v, "condition")
        return render_condition(store, c, asset_v)

    return cat
