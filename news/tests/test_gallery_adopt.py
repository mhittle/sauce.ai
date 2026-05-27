"""Route tests for gallery adopt de-duplication (BUG-025).

Adopting a shared algorithm whose name already matches one of the user's
profiles must reuse that profile (refreshing its weights + keywords and
re-activating it) instead of stacking a duplicate row in the switcher.
In-memory fakes for user_algorithms / algorithm_term_prefs /
algorithm_adoptions, same monkeypatch pattern as test_algo_profiles.
"""
import json
import itertools

import pytest

from app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    app = create_app()

    @app.before_request
    def _stub_user():
        from flask import g
        g.user = {"id": 42, "email": "t@x", "is_admin": 0}

    return app.test_client()


@pytest.fixture
def store(monkeypatch):
    algos = []                      # user_algorithms rows
    terms = []                      # algorithm_term_prefs rows
    adoptions = []                  # algorithm_adoptions rows
    listings = {}                   # shared_algorithms by id
    ids = itertools.count(1)
    clock = itertools.count(1)

    def _touch(r):
        r["updated_at"] = next(clock)

    def fake_query(sql, params=None, one=False):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id, name, weights_json, keywords_json from shared_algorithms"):
            (lid,) = params
            return listings.get(lid)
        if s.startswith("select id from user_algorithms where user_id = %s and name = %s"):
            uid, name = params
            m = [r for r in algos if r["user_id"] == uid and r["name"] == name]
            m.sort(key=lambda r: r["updated_at"], reverse=True)
            return ({"id": m[0]["id"]} if m else None) if one else m
        return None if one else []

    def fake_execute(sql, params=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("update user_algorithms set is_active = 0 where user_id = %s"):
            (uid,) = params
            for r in algos:
                if r["user_id"] == uid:
                    r["is_active"] = 0
        elif s.startswith("update user_algorithms set weights_json=%s, expression_text=%s, is_active=1"):
            wj, expr, aid, uid = params
            for r in algos:
                if r["id"] == aid and r["user_id"] == uid:
                    r["weights_json"] = wj
                    r["expression_text"] = expr
                    r["is_active"] = 1
                    _touch(r)
        elif s.startswith("insert into user_algorithms"):
            uid, name, wj, expr = params
            r = {"id": next(ids), "user_id": uid, "name": name,
                 "weights_json": wj, "expression_text": expr, "is_active": 1}
            _touch(r)
            algos.append(r)
            return r["id"]
        elif s.startswith("delete from algorithm_term_prefs where algorithm_id = %s"):
            (aid,) = params
            terms[:] = [t for t in terms if t["algorithm_id"] != aid]
        elif s.startswith("insert into algorithm_term_prefs"):
            aid, term, mode, weight = params
            terms.append({"algorithm_id": aid, "term": term,
                          "mode": mode, "weight": weight})
        elif s.startswith("insert into algorithm_adoptions"):
            lid, uid, ua_id = params
            adoptions.append({"shared_algorithm_id": lid, "user_id": uid,
                              "user_algorithm_id": ua_id})
        return 1

    class FakeConn:
        def commit(self):
            pass

    monkeypatch.setattr("app.routes.gallery.query", fake_query)
    monkeypatch.setattr("app.routes.gallery.execute", fake_execute)
    monkeypatch.setattr("app.routes.gallery.get_conn", lambda: FakeConn())

    def seed_algo(name, active=0, aid=None):
        r = {"id": aid or next(ids), "user_id": 42, "name": name,
             "weights_json": "{}", "expression_text": "", "is_active": active}
        r["updated_at"] = next(clock)
        algos.append(r)
        return r["id"]

    def seed_listing(lid, name, weights, keywords=None):
        listings[lid] = {
            "id": lid, "name": name,
            "weights_json": json.dumps(weights),
            "keywords_json": json.dumps(keywords or []),
        }

    return {"algos": algos, "terms": terms, "adoptions": adoptions,
            "seed_algo": seed_algo, "seed_listing": seed_listing}


def _active_ids(algos):
    return [r["id"] for r in algos if r["is_active"]]


def test_adopt_new_name_inserts_profile(client, store):
    store["seed_algo"]("Mine", active=1)
    store["seed_listing"](7, "Lefty", {"objectivity": 1.2})
    r = client.post("/gallery/7/adopt")
    assert r.status_code == 302
    lefties = [a for a in store["algos"] if a["name"] == "Lefty"]
    assert len(lefties) == 1
    assert _active_ids(store["algos"]) == [lefties[0]["id"]]
    assert len(store["adoptions"]) == 1


def test_adopt_same_name_reuses_profile_no_duplicate(client, store):
    store["seed_algo"]("Mine", active=1)
    existing = store["seed_algo"]("Lefty", active=0)
    store["seed_listing"](7, "Lefty", {"objectivity": 2.0},
                          keywords=[{"term": "crypto", "mode": "mute",
                                     "weight": 1.5}])
    r = client.post("/gallery/7/adopt")
    assert r.status_code == 302
    lefties = [a for a in store["algos"] if a["name"] == "Lefty"]
    assert len(lefties) == 1                       # reused, not duplicated
    assert lefties[0]["id"] == existing
    assert json.loads(lefties[0]["weights_json"])["objectivity"] == 2.0
    assert _active_ids(store["algos"]) == [existing]


def test_adopt_same_name_refreshes_keywords(client, store):
    existing = store["seed_algo"]("Lefty", active=1)
    store["terms"].append({"algorithm_id": existing, "term": "stale",
                           "mode": "mute", "weight": 1.5})
    store["seed_listing"](7, "Lefty", {"objectivity": 1.0},
                          keywords=[{"term": "fresh", "mode": "boost",
                                     "weight": 2.0}])
    client.post("/gallery/7/adopt")
    kept = [t for t in store["terms"] if t["algorithm_id"] == existing]
    assert [t["term"] for t in kept] == ["fresh"]   # old wiped, new applied
