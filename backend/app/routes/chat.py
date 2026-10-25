"""Asking questions (playground), conversation history, feedback, analytics."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import analytics, schemas
from ..db import get_session
from ..index import ask as run_ask
from ..models import Conversation, Feedback, KnowledgeBase, Message, User
from ..observability import record_answer
from ..security import current_user, kb_for

router = APIRouter(prefix="/api", tags=["chat"])


def answer_and_store(request: Request, db: Session, kb: KnowledgeBase, conv: Conversation, question: str) -> schemas.AnswerOut:
    """Shared by the playground and the public widget: store the question, answer it, store the answer."""
    t0 = time.perf_counter()
    db.add(Message(conversation_id=conv.id, kb_id=kb.id, role="user", text=question))
    res = run_ask(db, kb, question)
    ms = (time.perf_counter() - t0) * 1000
    a = res.answer
    msg = Message(
        conversation_id=conv.id, kb_id=kb.id, role="assistant", text=a.text, sources=res.passages,
        abstained=a.abstained, mode=a.mode, latency_ms=round(ms, 1),
    )  # fmt: skip
    db.add(msg)
    db.commit()
    record_answer(request, kb.id, "refused" if a.abstained else f"answered_{a.mode}", a.sources, ms)
    return schemas.AnswerOut(
        conversation_id=conv.id, message_id=msg.id, text=a.text, abstained=a.abstained, mode=a.mode,
        sources=[schemas.Passage(**p) for p in res.passages], note=a.note,
    )  # fmt: skip


@router.post("/kbs/{kb_id}/ask", response_model=schemas.AnswerOut)
def ask(kb_id: int, body: schemas.Ask, request: Request, user: User = Depends(current_user), db: Session = Depends(get_session)):
    kb = kb_for(db, user, kb_id)
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if conv is None or conv.kb_id != kb.id or conv.user_id != user.id:
            raise HTTPException(404, "conversation not found")
    else:
        conv = Conversation(kb_id=kb.id, user_id=user.id, channel="console")
        db.add(conv)
        db.flush()
    return answer_and_store(request, db, kb, conv, body.question)


@router.get("/kbs/{kb_id}/conversations", response_model=list[schemas.ConversationOut])
def conversations(
    kb_id: int,
    channel: str | None = Query(default=None, pattern="^(console|public)$"),
    only_problems: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    kb_for(db, user, kb_id)
    m = Message
    first_q = (
        select(m.text).where(m.conversation_id == Conversation.id, m.role == "user").order_by(m.id).limit(1).correlate(Conversation).scalar_subquery()
    )
    down = select(func.count()).select_from(Feedback).join(m, m.id == Feedback.message_id).where(m.conversation_id == Conversation.id, Feedback.rating == -1)
    stats = (
        select(
            m.conversation_id,
            func.count().label("n"),
            func.sum(case((m.abstained, 1), else_=0)).label("refused"),
        )
        .group_by(m.conversation_id)
        .subquery()
    )
    q = (
        select(Conversation, first_q, stats.c.n, stats.c.refused, down.correlate(Conversation).scalar_subquery())
        .join(stats, stats.c.conversation_id == Conversation.id)
        .where(Conversation.kb_id == kb_id)
        .order_by(Conversation.created_at.desc())
        .limit(limit)
    )
    if channel:
        q = q.where(Conversation.channel == channel)
    rows = db.execute(q).all()
    out = [
        schemas.ConversationOut(
            id=c.id, channel=c.channel, is_demo=c.is_demo, created_at=c.created_at, first_question=fq or "", messages=n, refused=int(r or 0), rating_down=d or 0
        )
        for c, fq, n, r, d in rows
    ]
    return [c for c in out if c.refused or c.rating_down] if only_problems else out


@router.get("/conversations/{conv_id}", response_model=list[schemas.MessageOut])
def conversation(conv_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)):
    conv = db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    kb_for(db, user, conv.kb_id)
    rows = db.execute(
        select(Message, Feedback.rating).outerjoin(Feedback, Feedback.message_id == Message.id).where(Message.conversation_id == conv.id).order_by(Message.id)
    ).all()
    return [schemas.MessageOut.model_validate(m).model_copy(update={"rating": r}) for m, r in rows]


@router.put("/messages/{message_id}/feedback", status_code=204)
def feedback(message_id: int, body: schemas.FeedbackIn, user: User = Depends(current_user), db: Session = Depends(get_session)):
    msg = db.get(Message, message_id)
    if msg is None or msg.role != "assistant":
        raise HTTPException(404, "answer not found")
    kb_for(db, user, msg.kb_id)
    save_feedback(db, msg, body)


def save_feedback(db: Session, msg: Message, body: schemas.FeedbackIn) -> None:
    """One rating per answer; rating again replaces it (PUT is idempotent)."""
    fb = db.scalar(select(Feedback).where(Feedback.message_id == msg.id))
    if fb is None:
        db.add(Feedback(message_id=msg.id, rating=body.rating, comment=body.comment.strip()))
    else:
        fb.rating, fb.comment = body.rating, body.comment.strip()
    db.commit()


@router.get("/kbs/{kb_id}/analytics")
def kb_analytics(kb_id: int, days: int = Query(default=30, ge=1, le=365), user: User = Depends(current_user), db: Session = Depends(get_session)):
    kb_for(db, user, kb_id)
    return {**analytics.overview(db, kb_id, days), "gaps": analytics.gaps(db, kb_id, days), "low_rated": analytics.low_rated(db, kb_id)}
