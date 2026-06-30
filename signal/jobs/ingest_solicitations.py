"""Ingest public bid-board solicitations (PRD PlanHub track).

    python jobs/ingest_solicitations.py [--source samgov] [--since YYYY-MM-DD]

Implemented: `samgov` (needs SAMGOV_API_KEY) and `bonfire` (public Bonfire/Euna
opportunities for a set of CA agencies — no key; requests-only). Other source
types (esbd-tx, vbs-fl, gpr-ga, cscr, bidnet, demandstar) are registered but
not yet implemented — they raise a clear NotImplementedError (see
signal/roadmap.md). `cscr` (Cal eProcure) is an InFlight-NLX/PeopleSoft SPA
that needs Playwright; `bonfire` is the lighter requests-friendly CA path.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
from datetime import datetime

from app.db import session_factory
from app.ingest.solicitations import run_solicitation_ingest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="samgov")
    ap.add_argument("--since", help="YYYY-MM-DD posted-from cutoff")
    args = ap.parse_args()
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None

    sess = session_factory()()
    try:
        result = run_solicitation_ingest(sess, args.source, since=since)
        print(f"{args.source}: {result['status']} "
              f"fetched={result['fetched']} upserted={result['upserted']}")
    finally:
        sess.close()


if __name__ == "__main__":
    main()
