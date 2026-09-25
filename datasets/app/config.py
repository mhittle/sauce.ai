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


def resolve_data_dir() -> Path:
    """Where the catalog lives. On Railway, an attached volume always wins:
    if DATASETS_DATA_DIR points anywhere outside the volume (e.g. "./data"
    pasted from .env.example, or a mount path that doesn't match), writing
    there would land on the container's ephemeral disk and be wiped on the
    next deploy, so we use the volume's mount path instead."""
    raw = Path(os.environ.get("DATASETS_DATA_DIR", _ROOT / "data"))
    vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if vol:
        try:
            inside = raw.resolve().is_relative_to(Path(vol).resolve())
        except (OSError, ValueError):
            inside = False
        if not inside:
            return Path(vol)
    return raw


def on_mounted_volume(path: Path) -> bool:
    """True if path sits on a separately mounted filesystem (not the
    container's root overlay)."""
    p = path.resolve()
    for candidate in (p, *p.parents):
        if candidate == Path("/"):
            return False
        if os.path.ismount(candidate):
            return True
    return False


def on_railway() -> bool:
    return any(os.environ.get(k) for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID",
                                           "RAILWAY_SERVICE_ID"))


@dataclass(frozen=True)
class Settings:
    # Storage: one SQLite catalog + a directory of downloaded flat files.
    data_dir: Path = field(default_factory=resolve_data_dir)
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
    # Claude assigns AI-list devices (brand-named, so name matching misses
    # them) to conditions, 40 per call, once per device.
    device_mapping: bool = _bool("DATASETS_DEVICE_MAPPING", True)
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
