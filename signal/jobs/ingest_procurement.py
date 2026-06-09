"""Ingest a config-driven procurement source (PRD PlanHub track, state/county/
local). Validate selectors first with jobs/validate_procurement_source.py.

    python jobs/ingest_procurement.py --slug ga-gpr [--all]
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse

from app.adapters.solicitations.config_source import (build_config_adapter,
                                                      get_source, load_sources)
from app.db import session_factory
from app.ingest.solicitations import run_ingest_adapter


def _run(sess, src) -> None:
    adapter = build_config_adapter(src)
    result = run_ingest_adapter(sess, src["slug"], adapter)
    print(f"  {src['slug']}: {result['status']} "
          f"fetched={result['fetched']} upserted={result['upserted']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true", help="ingest every active source")
    args = ap.parse_args()

    sess = session_factory()()
    try:
        if args.all:
            for src in load_sources():
                if src.get("active", True):
                    _run(sess, src)
        elif args.slug:
            src = get_source(args.slug)
            if not src:
                raise SystemExit(f"no source {args.slug!r}")
            _run(sess, src)
        else:
            print("sources:", [s["slug"] for s in load_sources()])
    finally:
        sess.close()


if __name__ == "__main__":
    main()
