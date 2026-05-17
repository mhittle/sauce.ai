"""Tests for the cold-start onboarding interview.

Pure-helper tests (app/onboarding.py) run without Flask. The route tests
mirror tests/test_signals.py: create_app + a stub user + monkeypatched
query/execute, no real DB.
"""
import json

import pytest

from app.onboarding import (
    LEAN_CHOICES, DEFAULT_LEAN_KEY, TRUSTED_SOURCE_WEIGHT,
    normalize_categories, lean_direction, build_onboarding_weights,
    top_trusted_sources,
)
from app.ranking import PRESETS, CATEGORIES


# ---- pure helpers --------------------------------------------------------

def test_normalize_categories_filters_unknown_and_dedupes():
    out = normalize_categories(["tech", "tech", "bogus", "world", ""])
    assert out == [c for c in CATEGORIES if c in ("tech", "world")]
    assert "bogus" not in out


def test_normalize_categories_empty_and_none():
    assert normalize_categories([]) == []
    assert normalize_categories(None) == []


def test_normalize_categories_uses_catalog_order():
    # input order shouldn't matter; output follows CATEGORIES order
    out = normalize_categories(["sports", "politics"])
    assert out == [c for c in CATEGORIES if c in ("sports", "politics")]


def test_lean_direction_known_keys():
    assert lean_direction("center") == 0.0
    assert lean_direction("left") < 0
    assert lean_direction("right") > 0
    assert lean_direction("center_left") < 0 < lean_direction("center_right")


def test_lean_direction_unknown_falls_back_to_center():
    assert lean_direction("nonsense") == 0.0
    assert lean_direction(None) == 0.0


def test_build_onboarding_weights_layers_on_balanced():
    w = build_onboarding_weights(categories=["tech", "science"], lean_key="left")
    base = PRESETS["balanced"]["weights"]
    # quality weights inherited from balanced
    assert w["objectivity"] == base["objectivity"]
    assert w["recency"] == base["recency"]
    # interview overlay applied
    assert w["category_filter"] == normalize_categories(["tech", "science"])
    assert w["political_lean_direction"] == lean_direction("left")


def test_build_onboarding_weights_defaults_are_balanced_centrist():
    w = build_onboarding_weights()
    assert w["category_filter"] == []
    assert w["political_lean_direction"] == 0.0


def test_build_onboarding_weights_does_not_mutate_presets():
    before = json.dumps(PRESETS["balanced"]["weights"], sort_keys=True)
    w = build_onboarding_weights(categories=["tech"], lean_key="right")
    w["objectivity"] = 999
    w["category_filter"].append("hacked")
    after = json.dumps(PRESETS["balanced"]["weights"], sort_keys=True)
    assert before == after
    assert "category_filter" not in PRESETS["balanced"]["weights"]


def test_top_trusted_sources_dedupes_by_name_keeping_best():
    rows = [
        {"name": "Reuters", "source_reputation": 0.7},
        {"name": "Reuters", "source_reputation": 0.92},
        {"name": "AP", "source_reputation": 0.9},
    ]
    out = top_trusted_sources(rows)
    names = [r["name"] for r in out]
    assert names == ["Reuters", "AP"]
    assert out[0]["source_reputation"] == 0.92


def test_top_trusted_sources_sorted_and_capped():
    rows = [{"name": f"S{i}", "source_reputation": i / 100} for i in range(30)]
    out = top_trusted_sources(rows, limit=5)
    assert len(out) == 5
    reps = [r["source_reputation"] for r in out]
    assert reps == sorted(reps, reverse=True)


def test_top_trusted_sources_tolerates_missing_fields():
    rows = [
        {"name": None, "source_reputation": 1.0},
        {"name": "X"},
        {"name": "Y", "source_reputation": 0.5},
    ]
    out = top_trusted_sources(rows)
    names = [r["name"] for r in out]
    assert "X" in names and "Y" in names and None not in names


# ---- route ---------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from app import create_app
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()

    @app.before_request
    def _stub_user():
        from flask import g
        g.user = {"id": 42, "email": "t@x", "is_admin": 0}

    return app.test_client()


@pytest.fixture
def store(monkeypatch):
    state = {"has_algo": False}
    executed = []
    src_pool = [
        {"id": 1, "name": "Reuters", "source_reputation": 0.92,
         "source_lean": 0.0, "category": "world"},
        {"id": 2, "name": "AP", "source_reputation": 0.9,
         "source_lean": 0.0, "category": "general"},
    ]

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if "count(*) as n from user_algorithms" in s:
            return {"n": 1 if state["has_algo"] else 0}
        if "from sources where owner_id is null and is_active = 1 order by" in s:
            return list(src_pool)
        if "select id from sources where id in" in s:
            ids = set(params or ())
            return [{"id": r["id"]} for r in src_pool if r["id"] in ids]
        return None if one else []

    def fake_execute(sql, params=None):
        executed.append((sql.strip().split()[0].upper(), sql, params))
        if sql.strip().lower().startswith("insert into user_algorithms"):
            state["has_algo"] = True
        return 1

    class FakeConn:
        def commit(self):
            pass

    monkeypatch.setattr("app.routes.algo.query", fake_query)
    monkeypatch.setattr("app.routes.algo.execute", fake_execute)
    monkeypatch.setattr("app.routes.algo.get_conn", lambda: FakeConn())
    return {"state": state, "executed": executed}


def test_get_renders_interview_when_no_algorithm(client, store):
    r = client.get("/algo/onboarding")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "set up your feed" in body.lower()
    assert "Reuters" in body


def test_get_redirects_to_editor_when_already_onboarded(client, store):
    store["state"]["has_algo"] = True
    r = client.get("/algo/onboarding")
    assert r.status_code == 302
    assert "/algo" in r.headers["Location"]


def test_post_creates_algorithm_and_boosts_valid_sources(client, store):
    r = client.post("/algo/onboarding", data={
        "categories": ["tech", "world"],
        "lean": "center_left",
        "sources": ["1", "999"],  # 999 isn't in the pool -> ignored
    })
    assert r.status_code == 302
    inserts = [e for e in store["executed"] if e[0] == "INSERT"]
    algo_ins = [e for e in inserts if "user_algorithms" in e[1].lower()]
    pref_ins = [e for e in inserts if "user_source_prefs" in e[1].lower()]
    assert len(algo_ins) == 1
    saved = json.loads(algo_ins[0][2][2])
    assert saved["category_filter"] == ["world", "tech"] or saved["category_filter"] == ["tech", "world"]
    assert saved["political_lean_direction"] == lean_direction("center_left")
    # only the valid source id (1) gets a boost row, not 999
    assert len(pref_ins) == 1
    assert pref_ins[0][2] == (42, 1, TRUSTED_SOURCE_WEIGHT)


def test_post_is_idempotent_when_already_onboarded(client, store):
    store["state"]["has_algo"] = True
    r = client.post("/algo/onboarding", data={"lean": "center"})
    assert r.status_code == 302
    assert not any(e[0] == "INSERT" for e in store["executed"])
