"""The shared Palo Alto Health Labs site header, as on paloaltohealthlabs.com.

Mirrors header() in mhittle/paloaltohealthlabs.com .github/scripts/apply_site_nav.py
(the main site's single source for its menu), with two differences for this host:
links point at the main site absolutely, and Datasets is the current item. Styles
and behaviour are static/site-nav.css and static/site-nav.js, copied from the main
site. Used by the app page (index.html) and the server-rendered pages (seo.py).
The header carries Fabrica's page action, "Get started", linking to its start page.
"""
from __future__ import annotations

MAIN = "https://paloaltohealthlabs.com"
BOOKING = "https://calendar.app.google/eJZVyYnoFJD67mGX9"
CTA = ("Get started", f"{MAIN}/fabrica/start/")

TOP = [  # (label, href, current)
    ("Fabrica", f"{MAIN}/fabrica/", False),
    ("Co-Scientist", f"{MAIN}/co-scientist/", False),
    ("Datasets", "/", True),
    ("The Brief", "https://thebrief.paloaltohealthlabs.com", False),
]
SERVICES = [
    ("Fractional CTO", "/fractional-cto/"),
    ("Vibe-coded app to HIPAA-ready", "/services/vibe-coded-app-to-hipaa/"),
    ("Clinical AI assessment", "/services/clinical-ai-assessment.html"),
    ("Expert data labeling", "/services/expert-clinical-labeling.html"),
    ("All services", "/#services"),
]
GUIDES = [
    ("HIPAA guide for vibe-coded apps", "/guides/vibe-coded-hipaa/"),
    ("2026 BAA matrix", "/guides/vibe-coded-hipaa/2026-baa-matrix/"),
    ("Stack Checker", "/guides/vibe-coded-hipaa/stack-checker/"),
    ("Resource hub", "/resources/"),
    ("Downloads", "/resources/downloads/"),
    ("Blog", "/blog/"),
]
MARK = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 13 H6 L8 8 L11 17 L14 10 L16 13 H22" '
        'fill="none" stroke="#2433D9" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>')
CARET = ('<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 4.2l4 4 4-4" fill="none" stroke="currentColor" '
         'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def header() -> str:
    def link(label: str, href: str, cur: bool) -> str:
        cls = ' pn-cur" aria-current="true' if cur else ""
        return f'\n      <a class="pn-l{cls}" href="{href}">{label}</a>'
    links = "".join(link(*t) for t in TOP)

    def col(title: str, items: list[tuple[str, str]]) -> str:
        return (f'<div class="pn-col"><span class="pn-h">{title}</span>'
                + "".join(f'<a href="{MAIN}{h}">{label}</a>' for label, h in items) + "</div>")

    return f'''<header class="pn pn-has-cta" id="site-nav">
  <div class="pn-in">
    <a class="pn-brand" href="{MAIN}/" aria-label="Palo Alto Health Labs home">{MARK}Palo Alto Health Labs</a>
    <button class="pn-toggle" type="button" aria-expanded="false" aria-controls="pn-links" hidden>Menu</button>
    <nav class="pn-links" id="pn-links" aria-label="Site">{links}
      <div class="pn-dd">
        <button class="pn-l pn-dd-t" type="button" aria-expanded="false" aria-controls="pn-panel">Services{CARET}</button>
        <div class="pn-panel" id="pn-panel">
          {col("Services", SERVICES)}
          {col("Guides and resources", GUIDES)}
          <div class="pn-foot"><a href="{MAIN}/about.html">About</a><a href="{BOOKING}" target="_blank" rel="noopener">Book a free call</a></div>
        </div>
      </div>
    </nav>
    <a class="pn-cta" href="{CTA[1]}">{CTA[0]}</a>
  </div>
</header>'''
