"""Database engine and sessions (SQLAlchemy 2, PostgreSQL)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def configure(url: str) -> None:
    """Point the app at another database (tests use a throw-away Postgres)."""
    global engine
    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal.configure(bind=engine)


def get_session() -> Iterator[Session]:
    """One session per request; committed by the route, rolled back if anything raises."""
    with SessionLocal() as s:
        try:
            yield s
        except Exception:
            s.rollback()
            raise
