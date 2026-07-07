"""Daily solicitation (bid) pipeline — the bid-side twin of daily_ingest.

    python jobs/daily_solicitations.py [--skip-classify]

Runs, in order, with per-source isolation (one failure never aborts the rest;
every run logs its own IngestRun):

  1. samgov  — federal bids, 7-day incremental lookback
  2. bonfire — CA agency opportunities
  3. every active config-driven procurement source (CivicPlus et al, --all)
  4. classify_solicitations — cabinetry scoring over new bid PDFs (bounded;
     needs ANTHROPIC_API_KEY on the service, else it no-ops with a note)

Called by daily_ingest after the permit run, so the existing Railway cron
picks it up with no infra change; also runnable standalone.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
from datetime import date, timedelta

from app.adapters.solicitations.config_source import (build_config_adapter,
                                                      load_sources)
from app.db import session_factory
from app.ingest.solicitations import run_ingest_adapter, run_solicitation_ingest

SAMGOV_LOOKBACK_DAYS = 7
CLASSIFY_LIMIT = 200


def run_all(sess, skip_classify: bool = False) -> None:
    # 1-2. API-backed sources (samgov needs SAMGOV_API_KEY; skip quietly if unset)
    for source in ("samgov", "bonfire"):
        try:
            since = (date.today() - timedelta(days=SAMGOV_LOOKBACK_DAYS)
                     if source == "samgov" else None)
            r = run_solicitation_ingest(sess, source, since=since)
            print(f"  {source}: {r['status']} fetched={r['fetched']} "
                  f"upserted={r['upserted']}")
        except Exception as exc:  # noqa: BLE001 - per-source boundary
            print(f"  {source}: error {str(exc)[:120]}")

    # 3. config-driven procurement sources (CivicPlus scale-out)
    active = [s for s in load_sources() if s.get("active", True)]
    print(f"  procurement: {len(active)} active sources")
    for src in active:
        try:
            r = run_ingest_adapter(sess, src["slug"], build_config_adapter(src))
            if r["status"] != "ok" or r["upserted"]:
                print(f"    {src['slug']}: {r['status']} "
                      f"upserted={r['upserted']}")
        except Exception as exc:  # noqa: BLE001
            print(f"    {src['slug']}: error {str(exc)[:120]}")

    # 4. cabinetry classification over the fresh rows (heavy: downloads PDFs)
    if skip_classify:
        return
    try:
        from app.ingest.classify import classify_solicitations
        r = classify_solicitations(sess, limit=CLASSIFY_LIMIT)
        print(f"  classify: classified={r['classified']} "
              f"flagged={r['flagged']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  classify: error {str(exc)[:120]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-classify", action="store_true")
    args = ap.parse_args()
    sess = session_factory()()
    try:
        print(f"daily_solicitations @ {date.today()}")
        run_all(sess, skip_classify=args.skip_classify)
    finally:
        sess.close()


if __name__ == "__main__":
    main()
