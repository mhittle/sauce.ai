"""Run one crawl session in the foreground — the cron / scheduler entry point.

    python -m jobs.crawl                       # broad crawl, DATASETS_BROAD_CRAWL_MINUTES (60)
    python -m jobs.crawl --minutes 30
    python -m jobs.crawl --query "pneumothorax chest x-ray"

Example crontab (nightly 02:00 UTC, 1-hour broad crawl):

    0 2 * * * cd /app && python -m jobs.crawl >> data/crawl.log 2>&1

Downloads queued during the crawl finish before the process exits.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.manager import CrawlManager  # noqa: E402
from app.store import Store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--query", help="targeted crawl for this request (default: broad)")
    ap.add_argument("--minutes", type=int, help="wall-clock budget")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    store = Store(settings.db_path)
    mgr = CrawlManager(store, settings)
    mode = "query" if args.query else "broad"
    minutes = args.minutes or (settings.query_crawl_minutes if args.query
                               else settings.broad_crawl_minutes)
    crawl_id = store.create_crawl(mode, args.query, minutes)
    mgr.run_crawl_blocking(crawl_id, mode, args.query, minutes)
    mgr.drain_downloads()
    c = store.get_crawl(crawl_id)
    print(f"crawl {crawl_id} {c['status']}: {len(c['hits'])} found, "
          f"{len(c['new_hits'])} new, tokens in/out "
          f"{c['input_tokens']}/{c['output_tokens']}")
    return 0 if c["status"] in ("done", "cancelled") else 1


if __name__ == "__main__":
    sys.exit(main())
