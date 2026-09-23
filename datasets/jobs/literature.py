"""Run the literature linker in the foreground (cron / one-off backfill).

The API process already runs it continuously in a background thread when
DATASETS_LITERATURE=true (default); use this where the API isn't running, or
to backfill faster:

    python -m jobs.literature --minutes 30
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crawler  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.literature import LiteratureWorker  # noqa: E402
from app.store import Store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=30)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    store = Store(settings.db_path)
    worker = LiteratureWorker(
        store, settings,
        client_factory=crawler.make_client if settings.anthropic_api_key else None)
    steps = worker.run_for(args.minutes * 60)
    print(f"{steps} steps; {store.literature_summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
