"""Bulk-import curated sources (PhysioNet, TCIA, OpenNeuro) into the catalog.

The API also runs these from the Crawls tab; use this for a one-off backfill
or a cron job:

    python -m jobs.importer physionet tcia openneuro
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crawler  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.importers import SOURCES, run_sources  # noqa: E402
from app.store import Store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sources", nargs="*", default=list(SOURCES), choices=list(SOURCES))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    store = Store(settings.db_path)
    factory = crawler.make_client if settings.anthropic_api_key else None
    print(json.dumps(run_sources(store, settings, args.sources, factory), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
