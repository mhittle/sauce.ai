import importlib

import pytest


def _reload_config():
    import app.config as cfg
    return importlib.reload(cfg)


def test_database_url_prefers_explicit(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    cfg = _reload_config()
    assert cfg.resolve_database_url() == "postgresql+psycopg://u:p@h:5432/d"


def test_database_url_default_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    cfg = _reload_config()
    assert cfg.resolve_database_url().startswith("postgresql+psycopg://signal:")


def test_database_url_from_pg_vars_encodes_special_chars(monkeypatch):
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import make_url
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PGHOST", "db.proxy.rlwy.net")
    monkeypatch.setenv("PGPORT", "22281")
    monkeypatch.setenv("PGUSER", "signal")
    monkeypatch.setenv("PGPASSWORD", "Ab+cd/ef=gh")   # URL-unsafe chars
    monkeypatch.setenv("PGDATABASE", "signal")
    cfg = _reload_config()
    url = cfg.resolve_database_url()
    parsed = make_url(url)             # must parse without ArgumentError
    assert parsed.password == "Ab+cd/ef=gh"
    assert parsed.host == "db.proxy.rlwy.net" and parsed.port == 22281


def teardown_module():
    # leave config in its env-default state for other tests
    _reload_config()
