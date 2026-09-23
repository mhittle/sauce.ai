"""Runtime configuration, read from the environment.

Plain stdlib so the pure core (metrics / grading / compile) imports without
the web stack. See phenotype/.env.example for the full list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    db_path: str = os.environ.get("PHENOTYPE_DB_PATH", "data/phenotype.db")
    public_base_url: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")

    worker_threads: int = _int("PHENOTYPE_WORKER_THREADS", 2)
    extract_concurrency: int = _int("PHENOTYPE_EXTRACT_CONCURRENCY", 4)
    max_records_cap: int = _int("PHENOTYPE_MAX_RECORDS_CAP", 400)
    max_extract_cap: int = _int("PHENOTYPE_MAX_EXTRACT_CAP", 40)
    jobs_per_hour_per_ip: int = _int("PHENOTYPE_JOBS_PER_HOUR_PER_IP", 6)
    http_cache_ttl_s: int = _int("PHENOTYPE_HTTP_CACHE_TTL_S", 7 * 86400)

    # Literature APIs. All are free; NCBI asks for an email + tool name and
    # raises the rate limit from 3/s to 10/s with an API key.
    ncbi_api_key: str | None = os.environ.get("NCBI_API_KEY")
    contact_email: str = os.environ.get("PHENOTYPE_CONTACT_EMAIL", "phenotype@sauce.ai")
    use_europepmc: bool = _bool("PHENOTYPE_USE_EUROPEPMC", True)

    # Models: a cheaper model screens many abstracts; the main model reads the
    # included papers and extracts algorithms + validation metrics.
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    anthropic_refusal_fallback: bool = _bool("ANTHROPIC_REFUSAL_FALLBACK", True)
    screen_model: str = os.environ.get("PHENOTYPE_SCREEN_MODEL", "anthropic:claude-sonnet-5")
    extract_model: str = os.environ.get("PHENOTYPE_EXTRACT_MODEL", "anthropic:claude-opus-5")

    smtp_host: str | None = os.environ.get("SMTP_HOST")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_user: str | None = os.environ.get("SMTP_USER")
    smtp_pass: str | None = os.environ.get("SMTP_PASS")
    smtp_from: str = os.environ.get("SMTP_FROM", "phenotype@sauce.ai")
    smtp_starttls: bool = _bool("SMTP_STARTTLS", True)


def get_settings() -> Settings:
    return Settings()
