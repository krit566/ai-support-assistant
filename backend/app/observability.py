"""Request IDs, one JSON log line per request, and in-process metrics.

Logs and metrics never contain question or answer text: questions can include personal data. The text is stored
only in the conversations table, which is access-controlled per workspace.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import Counter, defaultdict, deque

from fastapi import FastAPI, Request

log = logging.getLogger("helpdesk")

_lock = threading.Lock()
_requests: Counter = Counter()  # "GET /api/kbs/{kb_id}" -> count
_statuses: Counter = Counter()  # "2xx" / "4xx" / "5xx"
_latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
_answers: Counter = Counter()  # answered_extractive / answered_llm / refused


def _route(request: Request) -> str:
    # group by route template ("/api/kbs/{kb_id}") rather than the raw path, so ids do not explode the metrics
    r = request.scope.get("route")
    return f"{request.method} {getattr(r, 'path', request.url.path)}"


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        route = _route(request)
        with _lock:
            _requests[route] += 1
            _statuses[f"{response.status_code // 100}xx"] += 1
            _latency[route].append(ms)
        response.headers["X-Request-ID"] = rid
        log.info(json.dumps({"rid": rid, "route": route, "status": response.status_code, "ms": round(ms, 1)}))
        return response


def record_answer(request: Request, kb_id: int, outcome: str, sources: list[str], ms: float) -> None:
    with _lock:
        _answers[outcome] += 1
    rid = getattr(request.state, "request_id", None)
    log.info(json.dumps({"rid": rid, "event": "answer", "kb": kb_id, "outcome": outcome, "sources": sources, "ms": round(ms, 1)}))


def _pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 1)


def snapshot() -> dict:
    with _lock:
        lat = {k: list(v) for k, v in _latency.items()}
        total = sum(_answers.values())
        return {
            "requests": dict(_requests),
            "statuses": dict(_statuses),
            "latency_ms": {k: {"p50": _pct(v, 0.5), "p95": _pct(v, 0.95)} for k, v in lat.items()},
            "answers": dict(_answers),
            "refusal_rate": round(_answers["refused"] / total, 3) if total else 0.0,
        }
