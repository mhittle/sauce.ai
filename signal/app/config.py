"""Runtime configuration, read from the environment.

Plain stdlib (no pydantic) so jobs and the pure ingest core can import it
without pulling the web stack. See signal/.env.example for the full list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _flt(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def resolve_database_url() -> str:
    """Prefer an explicit DATABASE_URL; otherwise assemble one from discrete
    PG* vars, URL-encoding the password safely.

    The discrete-var path exists because hosts (Railway, etc.) generate
    passwords with URL-unsafe characters (`+ / = @ :`). Putting such a
    password straight into DATABASE_URL makes SQLAlchemy fail to parse the
    URL; setting PGPASSWORD raw and letting us encode it sidesteps that.
    """
    raw = os.environ.get("DATABASE_URL")
    if raw:
        return raw
    host = os.environ.get("PGHOST")
    if host:
        from sqlalchemy import URL
        return URL.create(
            "postgresql+psycopg",
            username=os.environ.get("PGUSER", "signal"),
            password=os.environ.get("PGPASSWORD"),
            host=host,
            port=int(os.environ.get("PGPORT", "5432")),
            database=os.environ.get("PGDATABASE", "signal"),
        ).render_as_string(hide_password=False)
    return "postgresql+psycopg://signal:signal@localhost:5432/signal"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=resolve_database_url)
    socrata_app_token: str | None = os.environ.get("SOCRATA_APP_TOKEN")
    paid_api_key: str | None = os.environ.get("SIGNAL_PAID_API_KEY")
    samgov_api_key: str | None = os.environ.get("SAMGOV_API_KEY")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    email_api_key: str | None = os.environ.get("EMAIL_API_KEY")
    crm_webhook_url: str | None = os.environ.get("CRM_WEBHOOK_URL")
    facility_lat: float = _flt("FACILITY_LAT", 33.7490)   # default: Atlanta
    facility_lng: float = _flt("FACILITY_LNG", -84.3880)
    shippable_radius_mi: float = _flt("SHIPPABLE_RADIUS_MI", 500.0)
    secret_key: str = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    cors_origins: str = os.environ.get("CORS_ORIGINS", "*")
    # Scribe connector: send a bid PDF to scribe to be quoted. The API URL +
    # shared service token are required for the handoff; the web URL is only
    # used to build a deep link back to the takeoff review screen.
    scribe_api_url: str | None = os.environ.get("SCRIBE_API_URL")
    scribe_service_token: str | None = os.environ.get("SCRIBE_SERVICE_TOKEN")
    scribe_web_url: str | None = os.environ.get("SCRIBE_WEB_URL")


def get_settings() -> Settings:
    return Settings()
