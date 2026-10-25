"""HTTP API.  uvicorn assistant.api:app --reload   ->  POST /ask {"question": "..."}

Observability: every response carries X-Request-ID; one JSON log line per question (never the question text, which
may contain personal data); /metrics reports latency percentiles and how often the assistant answered vs refused.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import Counter, deque
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .core import Assistant

log = logging.getLogger("assistant.access")
app = FastAPI(title="AI Knowledge & Support Assistant", version="1.1.0")
_bot = Assistant(use_llm=os.environ.get("USE_LLM", "").lower() in ("1", "true", "yes"))
_LOCK = threading.Lock()
_LAT: deque = deque(maxlen=1000)
_OUTCOMES: Counter = Counter()  # answered_extractive / answered_llm / refused


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


@app.post("/ask")
def ask(body: Ask, request: Request) -> dict:
    t0 = time.perf_counter()
    out = _bot.ask_dict(body.question)
    ms = (time.perf_counter() - t0) * 1000
    outcome = "refused" if out["abstained"] else f"answered_{out['mode']}"
    with _LOCK:
        _LAT.append(ms)
        _OUTCOMES[outcome] += 1
    log.info(json.dumps({"rid": request.headers.get("x-request-id"), "outcome": outcome, "sources": out["sources"], "ms": round(ms, 1)}))
    return out


def _p(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 1)


@app.get("/metrics")
def metrics() -> dict:
    with _LOCK:
        vals, outcomes = list(_LAT), dict(_OUTCOMES)
    total = sum(outcomes.values())
    return {
        "questions": total,
        "outcomes": outcomes,
        "refusal_rate": round(outcomes.get("refused", 0) / total, 3) if total else 0.0,
        "latency_ms": {"p50": _p(vals, 0.5), "p95": _p(vals, 0.95)},
    }


_PAGE = (Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home() -> str:
    return _PAGE  # a small chat page that calls POST /ask


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "chunks": len(_bot.chunks), "embedder": _bot.embedder.name, "thresholds": _bot.thresholds}
