"""Runtime configuration, read from the environment (stdlib only).

See datasets/.env.example for the full list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Storage: one SQLite catalog + a directory of downloaded flat files.
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("DATASETS_DATA_DIR", _ROOT / "data")))
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    model: str = os.environ.get("DATASETS_MODEL", "claude-opus-5")
    # Effort for the planner (one call per crawl) vs the crawl workers (many).
    planner_effort: str = os.environ.get("DATASETS_PLANNER_EFFORT", "high")
    worker_effort: str = os.environ.get("DATASETS_WORKER_EFFORT", "medium")
    # Server-side refusal fallback ("default" = Anthropic-routed; "off" disables).
    fallbacks: str = os.environ.get("DATASETS_FALLBACKS", "default")
    # Crawl sizing.
    query_crawl_minutes: int = _int("DATASETS_QUERY_CRAWL_MINUTES", 10)
    broad_crawl_minutes: int = _int("DATASETS_BROAD_CRAWL_MINUTES", 60)
    swarm_size: int = _int("DATASETS_SWARM_SIZE", 4)
    max_turns_per_agent: int = _int("DATASETS_MAX_TURNS", 30)
    max_concurrent_crawls: int = _int("DATASETS_MAX_CONCURRENT_CRAWLS", 2)
    # A search re-crawls only if the same query wasn't crawled this recently.
    recrawl_hours: int = _int("DATASETS_RECRAWL_HOURS", 24)
    # Downloads: flat files only, size-capped, public addresses only.
    download_enabled: bool = _bool("DATASETS_DOWNLOAD", True)
    max_download_mb: int = _int("DATASETS_MAX_DOWNLOAD_MB", 500)
    max_files_per_dataset: int = _int("DATASETS_MAX_FILES_PER_DATASET", 10)
    allow_private_hosts: bool = _bool("DATASETS_ALLOW_PRIVATE_HOSTS", False)
    cors_origins: str = os.environ.get("CORS_ORIGINS", "*")
    # Literature linker (background): articles that cite / mention each dataset.
    literature_enabled: bool = _bool("DATASETS_LITERATURE", True)
    openalex_api_key: str | None = os.environ.get("OPENALEX_API_KEY")
    openalex_mailto: str | None = os.environ.get("OPENALEX_MAILTO")
    lit_refresh_days: int = _int("DATASETS_LIT_REFRESH_DAYS", 30)
    lit_interval_sec: float = float(_int("DATASETS_LIT_INTERVAL_SEC", 2))
    lit_idle_sec: float = float(_int("DATASETS_LIT_IDLE_SEC", 300))
    # A name alias matching more papers than this is too generic; keep its
    # top-cited page only. 0 = no limit.
    lit_max_mention_hits: int = _int("DATASETS_LIT_MAX_MENTION_HITS", 20000)
    # FDA devices: openFDA key raises the 1,000 requests/day anonymous limit.
    openfda_api_key: str | None = os.environ.get("OPENFDA_API_KEY")
    devices_enabled: bool = _bool("DATASETS_DEVICES", True)
    fda_max_devices_per_condition: int = _int("DATASETS_FDA_MAX_DEVICES", 5000)
    device_interval_sec: float = float(_int("DATASETS_DEVICE_INTERVAL_SEC", 3))
    # LLM summaries of submission PDFs: "on_demand" (when a user opens one),
    # "all" (background, every submission — costs scale with the device count),
    # or "off".
    device_llm: str = os.environ.get("DATASETS_DEVICE_LLM", "on_demand")
    # FDA's "AI-Enabled Medical Devices" list (xlsx); synced weekly. The media
    # id changes when FDA republishes — override here if the default 404s.
    fda_ai_list_url: str = os.environ.get(
        "DATASETS_FDA_AI_LIST_URL", "https://www.fda.gov/media/178540/download?attachment")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "catalog.sqlite3"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"


def get_settings() -> Settings:
    return Settings()
