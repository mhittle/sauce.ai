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
