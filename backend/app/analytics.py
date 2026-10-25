"""Numbers for the analytics page, computed with SQL over the messages and feedback tables.

"Gaps" are questions the assistant refused. They are grouped by their most frequent informative word, which is
crude but explainable: each group is a candidate for a new help article.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import Date, and_, case, cast, func, select
from sqlalchemy.orm import Session, aliased

from assistant.embeddings import tokens

from .models import Feedback, Message

# extra filler words ignored when naming a gap topic (the engine's own stopword list is left unchanged)
GROUP_STOP = {"about", "after", "before", "get", "got", "need", "much", "many", "where", "why", "there", "still", "also", "please"}


def overview(db: Session, kb_id: int, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    a = Message
    in_range = and_(a.kb_id == kb_id, a.role == "assistant", a.created_at >= since)

    day = cast(a.created_at, Date)
    per_day = db.execute(
        select(day, func.count(), func.sum(case((a.abstained, 1), else_=0))).where(in_range).group_by(day).order_by(day)
    ).all()
    by_day = {d: (n, int(r or 0)) for d, n, r in per_day}
    series = []
    start = since.date()
    for i in range(days + 1):  # every day in the range, including days without questions
        d = start + timedelta(days=i)
        n, r = by_day.get(d, (0, 0))
        series.append({"date": d.isoformat(), "questions": n, "refused": r})

    total = sum(n for n, _ in by_day.values())
    refused = sum(r for _, r in by_day.values())
    fb = dict(
        db.execute(select(Feedback.rating, func.count()).join(a, a.id == Feedback.message_id).where(in_range).group_by(Feedback.rating)).all()
    )
    modes = dict(db.execute(select(a.mode, func.count()).where(in_range).group_by(a.mode)).all())
    p = db.execute(
        select(func.percentile_cont(0.5).within_group(a.latency_ms), func.percentile_cont(0.95).within_group(a.latency_ms)).where(in_range)
    ).one()
    return {
        "days": days,
        "questions": total,
        "answered": total - refused,
        "refused": refused,
        "refusal_rate": round(refused / total, 3) if total else 0.0,
        "feedback": {"up": fb.get(1, 0), "down": fb.get(-1, 0)},
        "modes": modes,
        # None when no answer in the range has a measured latency (seeded demo answers have none)
        "latency_ms": {"p50": None if p[0] is None else round(p[0], 1), "p95": None if p[1] is None else round(p[1], 1)},
        "series": series,
    }


def _question_for(db: Session, answer_ids: list[int]) -> dict[int, str]:
    """The user's question for each answer: the user message just before it in the same conversation."""
    u = aliased(Message)
    a = aliased(Message)
    prev = (
        select(func.max(u.id))
        .where(u.conversation_id == a.conversation_id, u.role == "user", u.id < a.id)
        .correlate(a)
        .scalar_subquery()
    )
    rows = db.execute(select(a.id, select(Message.text).where(Message.id == prev).scalar_subquery()).where(a.id.in_(answer_ids))).all()
    return {aid: q or "" for aid, q in rows}


def low_rated(db: Session, kb_id: int, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(Message.id, Message.text, Message.sources, Feedback.comment, Feedback.created_at)
        .join(Feedback, Feedback.message_id == Message.id)
        .where(Message.kb_id == kb_id, Feedback.rating == -1)
        .order_by(Feedback.created_at.desc())
        .limit(limit)
    ).all()
    qs = _question_for(db, [r[0] for r in rows])
    return [
        {"message_id": mid, "question": qs.get(mid, ""), "answer": text, "sources": [s["source"] for s in (src or [])], "comment": c, "at": at.isoformat()}
        for mid, text, src, c, at in rows
    ]


def gaps(db: Session, kb_id: int, days: int = 30, limit: int = 10) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    ids = db.scalars(
        select(Message.id).where(Message.kb_id == kb_id, Message.role == "assistant", Message.abstained, Message.created_at >= since)
    ).all()
    questions = [q for q in _question_for(db, list(ids)).values() if q]
    toks = [set(tokens(q)) - GROUP_STOP for q in questions]
    freq = Counter(t for ts in toks for t in ts)
    groups: dict[str, list[str]] = {}
    for q, ts in zip(questions, toks):
        if not ts:
            continue
        # the question joins the group of its most common word (ties: alphabetical, so results are stable)
        key = min(ts, key=lambda t: (-freq[t], t))
        groups.setdefault(key, []).append(q)
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:limit]
    return [{"topic": k, "count": len(v), "examples": list(dict.fromkeys(v))[:3]} for k, v in ranked]
