import json
import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.seo import PUBLIC_URL, ROBOTS, slugify
from app.store import Store


def ld_blocks(html):
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


@pytest.fixture()
def site(tmp_path):
    settings = Settings(data_dir=tmp_path, literature_enabled=False, devices_enabled=False,
                        compat_enabled=False)
    store = Store(settings.db_path)
    a, _ = store.upsert_dataset({
        "title": "Siena Scalp EEG Database", "url": "https://physionet.org/content/siena-scalp-eeg/1.0.0/",
        "source": "PhysioNet", "access_type": "open", "license": "Creative Commons Attribution 4.0",
        "description": "EEG recordings of 14 patients with epilepsy, with seizure annotations by experts.",
        "conditions": ["epilepsy"], "modalities": ["eeg"], "file_formats": ["edf"], "n_subjects": "14",
        "access_instructions": "1. Open the page.\n2. Download the files.",
        "download_urls": ["https://physionet.org/static/published-projects/siena-scalp-eeg/siena.zip"]})
    b, _ = store.upsert_dataset({
        "title": "MIMIC-IV", "url": "https://physionet.org/content/mimiciv/3.1/", "source": "PhysioNet",
        "access_type": "credentialed", "description": "Short.", "conditions": ["critical illness", "epilepsy"],
        "modalities": ["ehr"]})
    r, _ = store.upsert_dataset({"title": "dbGaP portal", "url": "https://www.ncbi.nlm.nih.gov/gap/",
                                 "source": "NCBI", "conditions": ["epilepsy"]})
    with store._write() as c:
        c.execute("UPDATE datasets SET kind = 'repository' WHERE id = ?", (r,))
    client = TestClient(create_app(settings, store=store))
    return client, store, a, b


def test_slugify():
    assert slugify("Sjögren's  Syndrome — Ü/Ç") == "sjogren-s-syndrome-u-c"
    assert slugify("--A  B--") == "a-b"
    s = slugify("x" * 50 + " " + "y" * 50)
    assert len(s) <= 80 and not s.endswith("-")


def test_robots_and_sitemap(site):
    client, store, a, b = site
    r = client.get("/robots.txt")
    assert r.status_code == 200 and r.text == ROBOTS
    assert r.text.startswith("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /files/\n\nSitemap: ")
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    locs = re.findall(r"<loc>(.*?)</loc>", r.text)
    st = client.get("/api/stats").json()
    # home + 2 hubs + every dataset (not repositories) + every condition with datasets
    n_conds = len(client.get("/api/conditions?with_datasets=true").json())
    assert len(locs) == 3 + st["datasets"] + n_conds == 3 + 2 + 2
    assert f"{PUBLIC_URL}/datasets/siena-scalp-eeg-database-{a}" in locs
    assert f"{PUBLIC_URL}/conditions/epilepsy" in locs
    assert not any("dbgap" in u for u in locs)
    assert "<lastmod>" in r.text


def test_dataset_page(site):
    client, store, a, b = site
    r = client.get(f"/datasets/siena-scalp-eeg-database-{a}")
    assert r.status_code == 200
    t = r.text
    assert "<title>Siena Scalp EEG Database dataset — access, papers &amp; FDA submissions | Palo Alto Health Labs</title>" in t
    assert f'<link rel="canonical" href="{PUBLIC_URL}/datasets/siena-scalp-eeg-database-{a}">' in t
    assert "<h1>Siena Scalp EEG Database</h1>" in t
    assert "seizure annotations" in t and "How to access" in t and "2. Download the files." in t
    assert 'rel="noopener"' in t and 'href="/conditions/epilepsy"' in t
    ld = ld_blocks(t)[0]
    assert ld["@type"] == "Dataset" and ld["name"] == "Siena Scalp EEG Database"
    assert ld["url"].endswith(f"-{a}") and ld["sameAs"].startswith("https://physionet.org")
    assert ld["isAccessibleForFree"] is True and ld["creator"] == {"@type": "Organization", "name": "PhysioNet"}
    assert ld["license"] == {"@type": "CreativeWork", "name": "Creative Commons Attribution 4.0"}
    assert ld["distribution"][0]["@type"] == "DataDownload" and len(ld["description"]) >= 50
    # missing fields are omitted, short descriptions are built from catalog facts
    ld = ld_blocks(client.get(f"/datasets/mimic-iv-{b}").text)[0]
    assert "license" not in ld and "distribution" not in ld and "isAccessibleForFree" not in ld
    assert len(ld["description"]) >= 50 and ld["description"].startswith("Short.")


def test_redirects_and_404s(site):
    client, store, a, b = site
    r = client.get(f"/datasets/wrong-slug-{a}", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == f"/datasets/siena-scalp-eeg-database-{a}"
    assert client.get(f"/datasets/{a}", follow_redirects=False).status_code == 301
    assert client.get("/datasets/whatever-000000000000").status_code == 404
    assert client.get("/datasets/x-<script>").status_code == 404
    assert client.get("/conditions/not-a-condition").status_code == 404
    assert client.get("/datasets/?page=99").status_code == 404
    assert client.get("/datasets", follow_redirects=False).headers["location"] == "/datasets/"
    # repositories render but aren't indexed
    with store._conn() as c:
        rid = c.execute("SELECT id FROM datasets WHERE kind = 'repository'").fetchone()[0]
    rr = client.get(f"/datasets/dbgap-portal-{rid}")
    assert rr.status_code == 200 and '<meta name="robots" content="noindex">' in rr.text
    assert 'content="noindex"' not in client.get(f"/datasets/siena-scalp-eeg-database-{a}").text


def test_condition_and_hubs(site):
    client, store, a, b = site
    r = client.get("/conditions/epilepsy")
    assert r.status_code == 200
    t = r.text
    assert "<title>Epilepsy datasets — open data, papers &amp; FDA clearances | Palo Alto Health Labs</title>" in t
    assert "<h1>Epilepsy datasets</h1>" in t
    assert 'href="/#/datasets?condition=epilepsy"' in t      # the SPA's condition route
    assert "<b>2</b> datasets for Epilepsy (<b>1</b> open access)" in t and "FDA 510(k)" in t and "De Novo" in t
    ld = ld_blocks(t)[0]
    assert ld["@type"] == "ItemList" and ld["numberOfItems"] == 2
    assert {i["name"] for i in ld["itemListElement"]} == {"Siena Scalp EEG Database", "MIMIC-IV"}
    h = client.get("/datasets/")
    assert h.status_code == 200 and "<h1>Datasets for medical AI</h1>" in h.text
    assert 'href="/conditions/epilepsy"' in h.text and ld_blocks(h.text)[0]["numberOfItems"] == 2
    c = client.get("/conditions/")
    assert "<h1>Medical conditions — datasets &amp; FDA activity</h1>" in c.text
    assert ld_blocks(c.text)[0]["numberOfItems"] == 2


def test_spa_and_api_unchanged(site):
    client, *_ = site
    r = client.get("/")
    assert r.status_code == 200 and 'src="/static/app.js?v=' in r.text
    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/datasets/browse?limit=1").json()["total"] == 2


def test_bing_and_indexnow_files(site):
    client, *_ = site
    r = client.get("/BingSiteAuth.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert r.text == ('<?xml version="1.0"?>\n<users>\n\t<user>EB4E3F5B02489117E4B4979A488800DF</user>\n'
                      '</users>')
    r = client.get("/4e7cb8cfba444e299c57c0d936696e24.txt")
    assert r.status_code == 200 and r.text == "4e7cb8cfba444e299c57c0d936696e24"
    assert r.headers["content-type"].startswith("text/plain")
    assert client.get("/robots.txt").text == ROBOTS


def test_shared_site_header(site):
    """Same header as paloaltohealthlabs.com (Fabrica etc.), Datasets current."""
    client, store, a, b = site
    for path in ("/", "/datasets/", f"/datasets/siena-scalp-eeg-database-{a}", "/conditions/epilepsy"):
        t = client.get(path).text
        assert t.count('<header class="pn pn-has-cta" id="site-nav">') == 1, path
        assert '<a class="pn-cta" href="https://paloaltohealthlabs.com/fabrica/start/">Get started</a>' in t
        assert '<a class="pn-l pn-cur" aria-current="true" href="/">Datasets</a>' in t
        for label in ("Fabrica", "Co-Scientist", "The Brief", "Services", "Fractional CTO", "Book a free call"):
            assert label in t, (path, label)
        assert 'href="https://paloaltohealthlabs.com/fabrica/"' in t
        assert re.search(r'href="/static/site-nav\.css\?v=[0-9a-f]+"', t)
        assert re.search(r'src="/static/site-nav\.js\?v=[0-9a-f]+"', t)
        assert '<header class="nav">' not in t and "seo-nav" not in t
    assert client.get("/static/site-nav.css").status_code == 200
