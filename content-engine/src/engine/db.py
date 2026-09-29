from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def init_engine(url: str | None = None) -> Engine:
    """(Re)configure the global engine. Tests call this with an in-memory URL."""
    global _engine, _SessionLocal
    url = url or config.db_url()
    kwargs = {}
    if url == "sqlite:///:memory:":
        from sqlalchemy.pool import StaticPool

        kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    _engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):  # enforce foreign keys in SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def engine() -> Engine:
    return _engine or init_engine()


def create_all() -> None:
    Base.metadata.create_all(engine())


def new_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
