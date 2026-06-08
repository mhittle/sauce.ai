"""APScheduler entrypoint for the daily pipeline (PRD §6 scheduling).

    python jobs/scheduler.py

Runs daily_ingest once a day. On Railway this can run as a separate worker
process, or swap for a cron schedule that invokes `python jobs/daily_ingest.py`
directly (see signal/INSTALL.md). Kept dependency-light: if APScheduler isn't
installed it explains how to use cron instead.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import os

from jobs import daily_ingest


def main():
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        raise SystemExit(
            "APScheduler not installed. Either `pip install apscheduler` or "
            "schedule `python jobs/daily_ingest.py` via cron (see INSTALL.md).")

    hour = int(os.environ.get("INGEST_HOUR_UTC", "8"))
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(daily_ingest.main, CronTrigger(hour=hour, minute=0),
                  id="daily_ingest", max_instances=1, coalesce=True)
    print(f"scheduler: daily_ingest scheduled at {hour:02d}:00 UTC")
    sched.start()


if __name__ == "__main__":
    main()
