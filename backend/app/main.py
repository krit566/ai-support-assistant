"""HelpDesk AI API.   uvicorn app.main:app --reload     (docs at /docs)"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import observability
from .config import settings
from .db import get_session
from .models import User
from .routes import auth, chat, kbs, public
from .security import require_admin

logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI(title="HelpDesk AI", version="2.0.0", description="Knowledge-base support assistant: answers from your documents, cites them, refuses when unsure.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)
observability.install(app)
for r in (auth.router, kbs.router, chat.router, public.router):
    app.include_router(r)


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_session)) -> dict:
    db.execute(text("select 1"))  # fails (500) if the database is unreachable, so the platform restarts or alerts
    return {"status": "ok", "embedder": settings.embedder, "llm": settings.use_llm}


@app.get("/metrics", tags=["meta"])
def metrics(_: User = Depends(require_admin)) -> dict:
    return observability.snapshot()
