"""Classify solicitations for casework/cabinetry from their bid-package PDFs.

    python jobs/classify_solicitations.py [--slug ga-gainesville] [--limit 100] [--reclassify]

Downloads + text-extracts each solicitation's attached PDFs, flags the ones
that definitively reference cabinetry/casework, and scores the rest. Heavy
(downloads PDFs) — use --limit / --slug to bound a run. Run after
ingest_procurement / ingest_solicitations.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse

from app.db import session_factory
from app.ingest.classify import classify_solicitations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="limit to one source_type")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reclassify", action="store_true",
                    help="re-run even if already classified")
    args = ap.parse_args()

    sess = session_factory()()
    try:
        result = classify_solicitations(sess, slug=args.slug, limit=args.limit,
                                        reclassify=args.reclassify)
        print(f"classified={result['classified']} "
              f"cabinetry_flagged={result['flagged']}")
    finally:
        sess.close()


if __name__ == "__main__":
    main()
