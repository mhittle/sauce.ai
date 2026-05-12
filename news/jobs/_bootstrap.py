"""Shared bootstrap for cron scripts. Sets up sys.path, logger, DB connection."""
import os
import sys
import logging
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from app.config import Config  # noqa: E402
from app.db import connect_standalone  # noqa: E402


def setup_logging(name):
    logs_dir = os.path.join(HERE, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(message)s"
    log_path = os.path.join(logs_dir, f"{name}.log")
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
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
