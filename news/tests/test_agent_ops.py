"""Unit tests for the HMAC prod-ops executor (agent_ops blueprint).

Covers the security-critical surface: signature verification
(valid / invalid / missing / stale), migration filename whitelist +
path-traversal blocking, and that verify-schema only ever runs a
parameterized information_schema SELECT (never caller SQL). Pure
helpers are tested without Flask; the routes use the create_app +
monkeypatched-DB pattern from test_signals.py / test_admin_ops.py.
"""

import json
import time

import pytest

from app import create_app
from app.routes import agent_ops as ops

SECRET = "unit-test-agent-ops-secret"


# --- pure helpers ---------------------------------------------------------

def test_signature_roundtrip():
    ts = str(int(time.time()))
    body = b'{"filename":"x.sql"}'
    sig = ops.compute_signature(SECRET, ts, body)
    assert ops.verify_signature(SECRET, ts, body, sig)


def test_signature_rejects_wrong_secret():
    ts = str(int(time.time()))
    body = b"{}"
    sig = ops.compute_signature("other-secret", ts, body)
    assert not ops.verify_signature(SECRET, ts, body, sig)


def test_signature_rejects_tampered_body():
    ts = str(int(time.time()))
    sig = ops.compute_signature(SECRET, ts, b'{"a":1}')
    assert not ops.verify_signature(SECRET, ts, b'{"a":2}', sig)


def test_signature_rejects_stale_timestamp():
    ts = str(int(time.time()) - 10_000)
    body = b"{}"
    sig = ops.compute_signature(SECRET, ts, body)
    assert not ops.verify_signature(SECRET, ts, body, sig, now=int(time.time()))


def test_signature_rejects_missing_parts():
    assert not ops.verify_signature("", "1", b"{}", "deadbeef")
    assert not ops.verify_signature(SECRET, "", b"{}", "deadbeef")
    assert not ops.verify_signature(SECRET, "1", b"{}", "")
    assert not ops.verify_signature(SECRET, "not-an-int", b"{}", "deadbeef")


def test_safe_migration_name():
    assert ops.safe_migration_name("2026-05-21-foo.sql")
    assert ops.safe_migration_name("a_b.c-1.sql")
    # path traversal / nested paths
    assert not ops.safe_migration_name("../secrets.sql")
    assert not ops.safe_migration_name("sub/dir.sql")
    assert not ops.safe_migration_name("/etc/passwd.sql")
    assert not ops.safe_migration_name("foo.sql.bak")
    assert not ops.safe_migration_name("foo.txt")
    assert not ops.safe_migration_name("")
    assert not ops.safe_migration_name("..")
    assert not ops.safe_migration_name("foo;DROP.sql")


def test_is_identifier():
    assert ops.is_identifier("article_features")
    assert ops.is_identifier("trending")
    assert not ops.is_identifier("a b")
    assert not ops.is_identifier("col; DROP TABLE x")
    assert not ops.is_identifier("a-b")
    assert not ops.is_identifier("")
    assert not ops.is_identifier("x" * 65)


def test_split_sql_statements_drops_comments_and_blanks():
    sql = (
        "-- leading comment\n"
        "CREATE TABLE t (id INT);\n"
        "\n"
        "-- trailing comment only\n"
    )
    stmts = ops.split_sql_statements(sql)
    assert stmts == ["CREATE TABLE t (id INT)"]


def test_split_sql_statements_multiple():
    sql = "ALTER TABLE a ADD COLUMN x INT;\nUPDATE a SET x = 0;\n"
    stmts = ops.split_sql_statements(sql)
    assert len(stmts) == 2
    assert stmts[0].startswith("ALTER TABLE a")
    assert stmts[1].startswith("UPDATE a")


# --- route fixtures -------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    monkeypatch.setenv("AGENT_OPS_SECRET", SECRET)
    app = create_app()
    app.config["AGENT_OPS_SECRET"] = SECRET
    app.config["DB_NAME"] = "testdb"
    return app


def _signed_headers(body: bytes):
    ts = str(int(time.time()))
    return {
        ops.TIMESTAMP_HEADER: ts,
        ops.SIGNATURE_HEADER: ops.compute_signature(SECRET, ts, body),
        "Content-Type": "application/json",
    }


# --- auth on routes -------------------------------------------------------

def test_route_rejects_missing_signature(app):
    r = app.test_client().post("/agent-ops/verify-schema", data=b"{}")
    assert r.status_code == 401


def test_route_rejects_bad_signature(app):
    body = b'{"table":"users","column":"id"}'
    headers = {
        ops.TIMESTAMP_HEADER: str(int(time.time())),
        ops.SIGNATURE_HEADER: "deadbeef",
        "Content-Type": "application/json",
    }
    r = app.test_client().post("/agent-ops/verify-schema", data=body, headers=headers)
    assert r.status_code == 401


def test_route_503_when_secret_unset(monkeypatch):
    monkeypatch.setattr("app.db.close_conn", lambda exc=None: None)
    monkeypatch.delenv("AGENT_OPS_SECRET", raising=False)
    app = create_app()
    app.config["AGENT_OPS_SECRET"] = ""
    body = b"{}"
    r = app.test_client().post(
        "/agent-ops/verify-schema", data=body, headers=_unsigned(body)
    )
    assert r.status_code == 503


def _unsigned(body):
    return {"Content-Type": "application/json"}


# --- run-migration whitelist ----------------------------------------------

def test_run_migration_rejects_traversal(app):
    body = json.dumps({"filename": "../../etc/passwd"}).encode()
    r = app.test_client().post(
        "/agent-ops/run-migration", data=body, headers=_signed_headers(body)
    )
    assert r.status_code == 400
    assert b"invalid migration filename" in r.data


def test_run_migration_rejects_nested_path(app):
    body = json.dumps({"filename": "sub/dir.sql"}).encode()
    r = app.test_client().post(
        "/agent-ops/run-migration", data=body, headers=_signed_headers(body)
    )
    assert r.status_code == 400


def test_run_migration_missing_file_404(app):
    body = json.dumps({"filename": "9999-does-not-exist.sql"}).encode()
    r = app.test_client().post(
        "/agent-ops/run-migration", data=body, headers=_signed_headers(body)
    )
    assert r.status_code == 404


def test_run_migration_applies_real_file(app, monkeypatch):
    executed = []

    class FakeCursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            executed.append(sql)

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append("__COMMIT__")

        def rollback(self):
            executed.append("__ROLLBACK__")

    monkeypatch.setattr("app.routes.agent_ops.get_conn", lambda: FakeConn())
    # Use a real migration file shipped in the repo.
    body = json.dumps({"filename": "2026-05-20-lab-votes.sql"}).encode()
    r = app.test_client().post(
        "/agent-ops/run-migration", data=body, headers=_signed_headers(body)
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["status"] == "ok"
    assert data["statements_run"] >= 1
    assert "__COMMIT__" in executed
    assert any("CREATE TABLE" in s for s in executed if isinstance(s, str))


def test_run_migration_rolls_back_on_error(app, monkeypatch):
    events = []

    class FakeCursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            raise RuntimeError("boom")

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            events.append("commit")

        def rollback(self):
            events.append("rollback")

    monkeypatch.setattr("app.routes.agent_ops.get_conn", lambda: FakeConn())
    body = json.dumps({"filename": "2026-05-20-lab-votes.sql"}).encode()
    r = app.test_client().post(
        "/agent-ops/run-migration", data=body, headers=_signed_headers(body)
    )
    assert r.status_code == 500
    assert "rollback" in events
    assert "commit" not in events


# --- verify-schema: no arbitrary SQL --------------------------------------

def test_verify_schema_rejects_non_identifier(app):
    body = json.dumps({"table": "users; DROP TABLE users", "column": "id"}).encode()
    r = app.test_client().post(
        "/agent-ops/verify-schema", data=body, headers=_signed_headers(body)
    )
    assert r.status_code == 400


def test_verify_schema_runs_parameterized_select_only(app, monkeypatch):
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params

        def fetchone(self):
            return {"n": 1}

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("app.routes.agent_ops.get_conn", lambda: FakeConn())
    body = json.dumps({"table": "article_features", "column": "trending"}).encode()
    r = app.test_client().post(
        "/agent-ops/verify-schema", data=body, headers=_signed_headers(body)
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data == {"table": "article_features", "column": "trending", "exists": True}
    # The only SQL run is the fixed information_schema SELECT, fully
    # parameterized — caller input never reaches the SQL string.
    assert "information_schema.columns" in captured["sql"].lower()
    assert captured["params"] == ("testdb", "article_features", "trending")
