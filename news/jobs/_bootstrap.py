"""Shared bootstrap for cron scripts. Sets up sys.path, logger, DB connection.

Cron scripts source this via:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _bootstrap import Config, get_conn, setup_logging, db_log, job_lock

so they work regardless of the caller's cwd.
"""
import fcntl
import os
import sys
import logging
from contextlib import contextmanager

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from app.config import Config  # noqa: E402


class AlreadyRunning(Exception):
    """Raised by job_lock when another instance of the job already holds the lock."""


def setup_logging(name):
    fmt = "%(asctime)s %(levelname)s %(message)s"
    handlers = [logging.StreamHandler()]
    try:
        logs_dir = os.path.join(HERE, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        handlers.insert(0, logging.FileHandler(os.path.join(logs_dir, f"{name}.log")))
    except OSError:
        pass
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    return logging.getLogger(name)


def db_log(conn, job, level, message):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_log (job, level, message) VALUES (%s, %s, %s)",
                (job, level, str(message)[:4000]),
            )
        conn.commit()
    except Exception:
        pass


def get_conn():
    from app.db import connect_standalone
    return connect_standalone(Config)


@contextmanager
def job_lock(name):
    """Per-job mutex backed by fcntl.flock. Wrap cron main() in this so a
    slow run doesn't get re-launched on top of itself when the next cron
    fires. Raises AlreadyRunning if the lock is held — the caller (cron
    entrypoint) should treat that as a successful no-op."""
    logs_dir = os.path.join(HERE, "logs")
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except OSError:
        pass
    lockpath = os.path.join(logs_dir, f"{name}.lock")
    fh = open(lockpath, "w")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            fh.close()
            raise AlreadyRunning(name) from e
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        fh.close()
