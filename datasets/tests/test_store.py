from app.store import Store, canonical_url, fts_query, normalize_query


def rec(**kw):
    base = {"title": "BraTS 2021", "url": "https://www.synapse.org/brats2021/",
            "source": "Synapse", "description": "Glioma MRI with segmentation masks.",
            "conditions": ["Brain Tumor", "glioma"], "modalities": ["mri"],
            "labels": "tumor segmentation masks", "access_type": "registration",
            "access_instructions": "Create a Synapse account.", "download_urls": [],
            "tags": ["challenge"]}
    base.update(kw)
    return base


def test_canonical_url_dedups_scheme_www_and_trailing_slash():
    assert canonical_url("https://www.Example.org/a/") == canonical_url("http://example.org/a")
    assert canonical_url("https://x.org/a#frag") == "x.org/a"


def test_upsert_is_idempotent_and_merges(tmp_path):
    s = Store(tmp_path / "c.db")
    i1, new1 = s.upsert_dataset(rec())
    i2, new2 = s.upsert_dataset(rec(url="http://synapse.org/brats2021", modalities=["ct"],
                                    license="CC BY", access_type="unknown", description=""))
    assert new1 and not new2 and i1 == i2
    d = s.get_dataset(i1)
    assert d["modalities"] == ["mri", "ct"]           # lists union
    assert d["license"] == "CC BY"                    # new scalar fills in
    assert d["description"].startswith("Glioma")      # empty doesn't clobber
    assert d["access_type"] == "registration"         # unknown doesn't clobber
    assert d["conditions"] == ["brain tumor", "glioma"]


def test_download_urls_keep_only_http(tmp_path):
    s = Store(tmp_path / "c.db")
    i, _ = s.upsert_dataset(rec(download_urls=["javascript:alert(1)", "https://x.org/a.csv"]))
    assert s.get_dataset(i)["download_urls"] == ["https://x.org/a.csv"]


def test_search_ranks_and_expands(tmp_path):
    s = Store(tmp_path / "c.db")
    a, _ = s.upsert_dataset(rec())
    b, _ = s.upsert_dataset(rec(title="MSSEG lesion challenge", url="https://msseg.org/",
                                conditions=["multiple sclerosis"],
                                description="MS lesion segmentation on brain MRI."))
    assert s.search("glioma MRI")[0] == a
    assert s.search("multiple sclerosis")[0] == b
    assert fts_query("the data of") is None
    assert s.search("the data") == []


def test_conditions_ranked_by_510k(tmp_path):
    s = Store(tmp_path / "c.db")
    s.upsert_dataset(rec())
    s.upsert_condition("pneumothorax", "Pneumothorax", ["ptx"], ["pneumothorax"])
    s.set_condition_510k("pneumothorax", 15)
    s.set_condition_510k("brain tumor", 3)
    ranked = s.conditions_ranked()
    assert [r["name"] for r in ranked][:2] == ["pneumothorax", "brain tumor"]
    assert ranked[1]["n_datasets"] == 1
    assert [r["name"] for r in s.conditions_ranked(only_with_datasets=True)] == \
        ["brain tumor", "glioma"]
    assert s.match_conditions("PTX on chest x-ray") == ["pneumothorax"]


def test_crawl_memo(tmp_path):
    s = Store(tmp_path / "c.db")
    i, _ = s.upsert_dataset(rec())
    cid = s.create_crawl("query", "Glioma MRI", 5)
    s.update_crawl(cid, plan={"conditions": [{"name": "glioma", "synonyms": ["gbm"]}]},
                   status="done")
    s.add_crawl_hit(cid, i, True)
    memo = s.memo_for_query("mri   glioma")               # same normalized query
    assert memo["dataset_ids"] == [i]
    assert memo["expansion_terms"] == ["glioma", "gbm"]
    assert s.recent_crawl_for("glioma mri", 24)["id"] == cid
    assert normalize_query("MRI, glioma!") == "glioma mri"
    s.update_crawl(cid, status="failed")
    assert s.recent_crawl_for("glioma mri", 24) is None     # failures don't memoize


def test_mark_stale(tmp_path):
    s = Store(tmp_path / "c.db")
    cid = s.create_crawl("broad", None, 60)
    s.update_crawl(cid, status="running")
    s.mark_stale_crawls()
    assert s.get_crawl(cid)["status"] == "interrupted"


def test_condition_display_labels():
    from app.store import condition_display
    assert condition_display("parkinson's disease") == "Parkinson's Disease"
    assert condition_display("copd") == "COPD"
    assert condition_display("covid-19") == "COVID-19"
    assert condition_display("als-ftd") == "ALS-FTD"


def test_condition_synonyms_canonicalized_and_merged_on_open(tmp_path):
    import sqlite3
    s = Store(tmp_path / "c.db")
    a, _ = s.upsert_dataset(rec(conditions=["COPD"]))
    assert s.get_dataset(a)["conditions"] == ["chronic obstructive pulmonary disease"]
    s.upsert_condition("chronic obstructive pulmonary disease")
    s.set_condition_510k("chronic obstructive pulmonary disease", 3)
    # A catalog written before the alias map existed: rows under "copd".
    con = sqlite3.connect(tmp_path / "c.db")
    b = "b" * 12
    con.execute("INSERT INTO datasets (id, canonical_url, url, title, conditions, first_seen,"
                " last_seen) VALUES (?, 'x.org/b', 'https://x.org/b', 'B', '[\"copd\", \"asthma\"]',"
                " '2026', '2026')", (b,))
    con.execute("INSERT INTO dataset_conditions VALUES (?, 'copd')", (b,))
    con.execute("INSERT INTO conditions (name, display, synonyms, fda_terms, fda_510k_count)"
                " VALUES ('copd', 'Copd', '[]', '[\"copd\"]', 9)")
    con.commit(); con.close()
    s = Store(tmp_path / "c.db")
    names = {r["name"]: r for r in s.conditions_ranked()}
    assert "copd" not in names
    copd = names["chronic obstructive pulmonary disease"]
    assert copd["n_datasets"] == 2 and copd["openfda_510k"] == 9
    assert "copd" in s.get_condition("COPD")["synonyms"]
    assert s.get_dataset(b)["conditions"] == ["chronic obstructive pulmonary disease", "asthma"]


def test_repositories_are_flagged_and_not_counted_as_datasets(tmp_path):
    from app.store import guess_kind
    assert guess_kind("https://dbgap.ncbi.nlm.nih.gov/home/", "dbGaP") == "repository"
    assert guess_kind("https://vivli.org/", "Vivli Center") == "repository"
    assert guess_kind("https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=phs1",
                      "PCGC cohort (dbGaP phs001194)") == "dataset"
    assert guess_kind("https://physionet.org/content/mitdb/1.0.0/", "MIT-BIH") == "dataset"
    s = Store(tmp_path / "c.db")
    s.upsert_dataset(rec())
    r, _ = s.upsert_dataset(rec(title="dbGaP", url="https://dbgap.ncbi.nlm.nih.gov/home/",
                                conditions=["glioma"]))
    assert s.get_dataset(r)["kind"] == "repository"
    assert (s.stats()["datasets"], s.stats()["repositories"]) == (1, 1)
    glioma = next(x for x in s.conditions_ranked() if x["name"] == "glioma")
    assert (glioma["n_datasets"], glioma["n_repositories"]) == (1, 1)
    # The agent's own classification wins over the URL guess.
    k, _ = s.upsert_dataset(rec(url="https://example.org/archive", kind="repository"))
    assert s.get_dataset(k)["kind"] == "repository"


def test_prune_literature_noise(tmp_path):
    s = Store(tmp_path / "c.db")
    repo, _ = s.upsert_dataset(rec(title="dbGaP", url="https://dbgap.ncbi.nlm.nih.gov/"))
    ds = [s.upsert_dataset(rec(title=f"PhysioNet DB {i}", url=f"https://physionet.org/content/db{i}/"))[0]
          for i in range(3)]
    own, _ = s.upsert_dataset(rec(title="Own", url="https://own.org/"))
    s.upsert_article({"id": "doi:platform", "doi": "10.1161/01.cir.101.23.e215", "title": "PhysioNet"})
    s.upsert_article({"id": "doi:own", "doi": "10.1/own", "title": "Own dataset paper"})
    for i, title in enumerate(["citer", "namer", "seurat", "own citer"]):
        s.upsert_article({"id": f"p{i}", "title": title})
    for d in ds:
        s.link_article(d, "doi:platform", "descriptor", "llm")
        s.link_article(d, "p0", "cites", "epmc_cites")
    s.link_article(ds[0], "p1", "mentions", "epmc_mentions")
    s.link_article(repo, "p2", "mentions", "epmc_mentions")
    s.link_article(own, "doi:own", "descriptor", "llm")
    s.link_article(own, "p3", "cites", "epmc_cites")
    assert "doi:platform" in s.platform_descriptor_ids()
    out = s.prune_literature_noise()
    assert out["repository_links"] == 1 and out["platform_links"] == 3
    assert out["datasets_reharvested"] == 3 and out["orphan_articles"] == 2   # p0, p2
    assert [a["id"] for a in s.dataset_articles(ds[0])["items"]] == ["doi:platform", "p1"]
    assert s.dataset_articles(repo)["total"] == 0
    assert [a["id"] for a in s.dataset_articles(own)["items"]] == ["doi:own", "p3"]
    assert s.run_once("k", lambda: {"n": 1}) == {"n": 1} and s.run_once("k", lambda: 2) is None
