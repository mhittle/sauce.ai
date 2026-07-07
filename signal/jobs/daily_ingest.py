"""Daily ingest across all active jurisdictions (PRD §6, §9 daily run).

    python jobs/daily_ingest.py [--since YYYY-MM-DD] [--slug <jurisdiction>]
                                [--no-solicitations]

Pulls each active jurisdiction through its adapter, upserts permits, dedups
into projects, recomputes signals, and scores. One jurisdiction failing does
not abort the rest (each run_ingest logs its own IngestRun).

After the permit run it also runs the daily solicitation (bid) pipeline —
samgov + bonfire + active procurement sources + cabinetry classification
(see jobs/daily_solicitations.py) — so the existing daily cron covers both
tracks. Suppress with --no-solicitations (or when running a single --slug).
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
from datetime import date, datetime

from sqlalchemy import text

from app.db import session_factory
from app.ingest.runner import run_ingest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD incremental cutoff")
    ap.add_argument("--slug", help="limit to one jurisdiction slug")
    ap.add_argument("--no-solicitations", action="store_true",
                    help="skip the daily solicitation (bid) pipeline")
    args = ap.parse_args()
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None

    sess = session_factory()()
    try:
        q = "SELECT * FROM jurisdictions WHERE active = TRUE"
        params = {}
        if args.slug:
            q += " AND slug = :slug"; params["slug"] = args.slug
        rows = sess.execute(text(q), params).all()
        print(f"daily_ingest: {len(rows)} jurisdiction(s) @ {date.today()}")
        for row in rows:
            result = run_ingest(sess, row, since=since)
            print(f"  {row.slug}: {result['status']} "
                  f"fetched={result['fetched']} upserted={result['upserted']} "
                  f"projects={result['projects_touched']}")

        # Bid-side daily pipeline (skipped for targeted single-slug runs).
        if not args.no_solicitations and not args.slug:
            from jobs.daily_solicitations import run_all
            print("daily_solicitations:")
            run_all(sess)
    finally:
        sess.close()


if __name__ == "__main__":
    main()
