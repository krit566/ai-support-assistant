"""Tests run against a real PostgreSQL, never SQLite, so they exercise the same SQL as production
(JSONB, arrays, percentile_cont, ON DELETE CASCADE).

- TEST_DATABASE_URL / DATABASE_URL set (CI: a postgres service container) -> a fresh database is created on it
- otherwise an embedded PostgreSQL is started with `pgserver` (pip install pgserver), no installation needed

The schema is built by running the Alembic migrations, so the migrations are tested too.
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def _server_url() -> tuple[str, object | None]:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url, None
    import pgserver

    srv = pgserver.get_server(tempfile.mkdtemp(prefix="helpdesk-test-"), cleanup_mode="stop")
    return srv.get_uri(), srv


@pytest.fixture(scope="session")
def database_url():
    from sqlalchemy import create_engine, text

    from app.config import _db_url

    base, srv = _server_url()
    base = _db_url(base)
    name = f"helpdesk_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = base.rsplit("/", 1)[0] + "/" + name

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")

    from app import db

    db.configure(url)
    yield url

    db.engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()
    if srv is not None:
        srv.cleanup()


@pytest.fixture()
def client(database_url):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app import db
    from app.index import cache
    from app.main import app
    from app.ratelimit import limiter

    yield TestClient(app)
    # every test starts from empty tables
    with db.engine.begin() as c:
        c.execute(text("TRUNCATE workspaces, users, knowledge_bases, documents, chunks, api_keys, conversations, messages, feedback RESTART IDENTITY CASCADE"))
    cache._cache.clear()
    limiter.reset()
