"""Runtime configuration, read from the environment.

Plain stdlib (no pydantic) so jobs and the pure ingest core can import it
without pulling the web stack. See signal/.env.example for the full list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _flt(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://signal:signal@localhost:5432/signal")
    socrata_app_token: str | None = os.environ.get("SOCRATA_APP_TOKEN")
    paid_api_key: str | None = os.environ.get("SIGNAL_PAID_API_KEY")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    email_api_key: str | None = os.environ.get("EMAIL_API_KEY")
    crm_webhook_url: str | None = os.environ.get("CRM_WEBHOOK_URL")
    facility_lat: float = _flt("FACILITY_LAT", 33.7490)   # default: Atlanta
    facility_lng: float = _flt("FACILITY_LNG", -84.3880)
    shippable_radius_mi: float = _flt("SHIPPABLE_RADIUS_MI", 500.0)
    secret_key: str = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    cors_origins: str = os.environ.get("CORS_ORIGINS", "*")


def get_settings() -> Settings:
    return Settings()
