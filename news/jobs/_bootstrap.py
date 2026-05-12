"""Shared bootstrap for cron scripts. Sets up sys.path, logger, DB connection.

Cron scripts source this via:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _bootstrap import Config, get_conn, setup_logging, db_log

so they work regardless of the caller's cwd.
"""
import os
import sys
import logging

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from app.config import Config  # noqa: E402
from app.db import connect_standalone  # noqa: E402


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
    return connect_standalone(Config)
