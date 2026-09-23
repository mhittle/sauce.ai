"""Runtime configuration, read from the environment.

Plain stdlib so the pure core (catalog / metrics / orchestrator) imports
without the web stack. See redteam/.env.example for the full list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _flt(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [s.strip() for s in os.environ.get(name, default).split(",") if s.strip()]


@dataclass(frozen=True)
class Settings:
    db_path: str = os.environ.get("REDTEAM_DB_PATH", "data/redteam.db")
    public_base_url: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")

    # Billing: free tier for now. Per-trial price is wired through quoting
    # and the report so turning on charging is a config change, not a rebuild.
    free_trial_limit: int = _int("REDTEAM_FREE_TRIAL_LIMIT", 100)
    price_per_trial_usd: float = _flt("REDTEAM_PRICE_PER_TRIAL_USD", 0.0)

    max_turns_cap: int = _int("REDTEAM_MAX_TURNS_CAP", 20)
    worker_threads: int = _int("REDTEAM_WORKER_THREADS", 4)
    trial_concurrency: int = _int("REDTEAM_TRIAL_CONCURRENCY", 4)
    allow_private_targets: bool = _bool("REDTEAM_ALLOW_PRIVATE_TARGETS")

    # Provider credentials for the attacker / judge ensembles. The target's
    # credentials come from the researcher per run and are never persisted.
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    llama_api_key: str | None = os.environ.get("LLAMA_API_KEY")
    llama_base_url: str = os.environ.get("LLAMA_BASE_URL", "https://api.together.xyz/v1")
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY")
    gemini_base_url: str = os.environ.get(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    anthropic_refusal_fallback: bool = _bool("ANTHROPIC_REFUSAL_FALLBACK", True)

    default_attackers: list[str] = field(
        default_factory=lambda: _list("REDTEAM_DEFAULT_ATTACKERS", "anthropic:claude-sonnet-5"))
    default_arbiter: str = os.environ.get("REDTEAM_DEFAULT_ARBITER", "anthropic:claude-opus-5")
    default_judges: list[str] = field(
        default_factory=lambda: _list("REDTEAM_DEFAULT_JUDGES", "anthropic:claude-opus-5"))

    # Critical Harm Event (CHE) measurement — additive, off unless enabled.
    che_enabled: bool = _bool("REDTEAM_CHE_ENABLED", True)
    che_screen_threshold: float = _flt("REDTEAM_CHE_SCREEN_THRESHOLD", 0.3)
    che_neg_sample_rate: float = _flt("REDTEAM_CHE_NEG_SAMPLE_RATE", 0.10)
    che_bootstrap_reps: int = _int("REDTEAM_CHE_BOOTSTRAP_REPS", 2000)
    che_min_cell_n: int = _int("REDTEAM_CHE_MIN_CELL_N", 30)
    che_screener_model: str = os.environ.get("REDTEAM_CHE_SCREENER_MODEL", "anthropic:claude-opus-5")
    che_require_clinician_validation_for_headline: bool = _bool(
        "REDTEAM_CHE_REQUIRE_CLINICIAN_VALIDATION", True)

    smtp_host: str | None = os.environ.get("SMTP_HOST")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_user: str | None = os.environ.get("SMTP_USER")
    smtp_pass: str | None = os.environ.get("SMTP_PASS")
    smtp_from: str = os.environ.get("SMTP_FROM", "redteam@sauce.ai")
    smtp_starttls: bool = _bool("SMTP_STARTTLS", True)


def get_settings() -> Settings:
    return Settings()
