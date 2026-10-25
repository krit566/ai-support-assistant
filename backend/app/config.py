"""Settings, read once from environment variables. Secrets (JWT_SECRET, LLM keys) are never given defaults that work
in production: the app refuses to start outside development without a real JWT_SECRET."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    jwt_minutes: int
    max_upload_bytes: int
    public_rate_per_minute: int
    use_llm: bool
    embedder: str
    cors_origins: list[str]
    env: str


def _db_url(raw: str) -> str:
    # Render and Heroku hand out "postgres://..." URLs; SQLAlchemy needs the driver named explicitly.
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


def load() -> Settings:
    env = os.environ.get("APP_ENV", "development")
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        if env != "development":
            raise RuntimeError("JWT_SECRET must be set outside development")
        secret = "dev-only-secret-change-me-not-for-production"
    return Settings(
        database_url=_db_url(os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/helpdesk")),
        jwt_secret=secret,
        jwt_minutes=int(os.environ.get("JWT_MINUTES", "480")),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
        public_rate_per_minute=int(os.environ.get("PUBLIC_RATE_PER_MINUTE", "20")),
        use_llm=os.environ.get("USE_LLM", "").lower() in ("1", "true", "yes"),
        embedder=os.environ.get("EMBEDDER", "lsa"),
        cors_origins=[o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5183").split(",") if o],
        env=env,
    )


settings = load()
