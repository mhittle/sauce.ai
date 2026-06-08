"""SQLAlchemy engine + session (sync, psycopg3).

Imported only by the web/jobs layer, never by the pure ingest/signal core,
so tests can exercise that core without a database.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True,
                                future=True)
        _SessionLocal = sessionmaker(bind=_engine, class_=Session,
                                     expire_on_commit=False)
    return _engine


def session_factory():
    if _SessionLocal is None:
        engine()
    return _SessionLocal


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    sess = session_factory()()
    try:
        yield sess
    finally:
        sess.close()
