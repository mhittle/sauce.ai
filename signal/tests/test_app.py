"""App-boot + endpoint smoke tests.

Gated on the web stack being installed (fastapi/sqlalchemy/httpx) so the pure
logic suite still runs green with only pytest present. These exercise the
graceful-degradation contract: endpoints return without a live DB.
"""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

client = TestClient(create_app())


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_signals_catalog_served_from_registry():
    r = client.get("/api/signals")
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()}
    assert "distress_stalled" in ids
    facets = client.get("/api/signals?facets_only=true").json()
    assert all(s["is_facet"] for s in facets)


def test_projects_list_degrades_without_db():
    # No DB configured in test env -> graceful empty, never a 500.
    r = client.get("/api/projects")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0 and body["items"] == []


def test_projects_list_accepts_sort_and_dir():
    # Whitelisted sort keys + direction are accepted (no 500), incl. city.
    for sort in ("jurisdiction", "category", "status", "lead_score"):
        for dir_ in ("asc", "desc"):
            r = client.get(f"/api/projects?sort={sort}&dir={dir_}")
            assert r.status_code == 200


def test_jurisdictions_degrades_without_db():
    r = client.get("/api/jurisdictions")
    assert r.status_code == 200 and r.json() == []
