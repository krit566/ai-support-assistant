"""The public chat widget: anyone with a knowledge base's publishable key can ask questions, nothing else.

The key is meant to be embedded in a web page, so it is not a secret in the strong sense. What protects the
knowledge base: the key works only for asking (no reading documents or analytics), only for its own knowledge
base, can be revoked, and is rate-limited per key.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_session
from ..models import ApiKey, Conversation, KnowledgeBase, Message
from ..ratelimit import limiter
from ..security import hash_key
from .chat import answer_and_store, save_feedback

router = APIRouter(prefix="/api/public", tags=["public widget"])


def _kb_and_key(db: Session, slug: str, key: str | None) -> tuple[KnowledgeBase, ApiKey]:
    kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.slug == slug))
    if kb is None:
        raise HTTPException(404, "assistant not found")
    k = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(key or "")))
    # one message for every key problem (missing, wrong, revoked, other knowledge base): nothing to learn from errors
    if k is None or k.kb_id != kb.id or k.revoked_at is not None:
        raise HTTPException(401, "invalid or revoked API key")
    return kb, k


@router.get("/kbs/{slug}", response_model=schemas.PublicKb)
def info(slug: str, x_api_key: str | None = Header(default=None), db: Session = Depends(get_session)):
    kb, _ = _kb_and_key(db, slug, x_api_key)
    return schemas.PublicKb(name=kb.name, description=kb.description, team_name=kb.team_name)


@router.post("/kbs/{slug}/ask", response_model=schemas.AnswerOut)
def ask(slug: str, body: schemas.PublicAsk, request: Request, x_api_key: str | None = Header(default=None), db: Session = Depends(get_session)):
    kb, key = _kb_and_key(db, slug, x_api_key)
    allowed, retry_after = limiter.allow(f"key:{key.id}", key.rate_per_minute)
    if not allowed:
        return JSONResponse(
            {"detail": f"too many questions; try again in {retry_after} s"}, status_code=429, headers={"Retry-After": str(retry_after)}
        )
    key.last_used_at = datetime.now(timezone.utc)
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        # a widget conversation can only be continued with the same key that started it
        if conv is None or conv.api_key_id != key.id:
            raise HTTPException(404, "conversation not found")
    else:
        conv = Conversation(kb_id=kb.id, api_key_id=key.id, channel="public")
        db.add(conv)
        db.flush()
    return answer_and_store(request, db, kb, conv, body.question)


@router.put("/kbs/{slug}/messages/{message_id}/feedback", status_code=204)
def feedback(slug: str, message_id: int, body: schemas.FeedbackIn, x_api_key: str | None = Header(default=None), db: Session = Depends(get_session)):
    kb, key = _kb_and_key(db, slug, x_api_key)
    msg = db.get(Message, message_id)
    conv = db.get(Conversation, msg.conversation_id) if msg else None
    if msg is None or msg.role != "assistant" or conv is None or conv.api_key_id != key.id:
        raise HTTPException(404, "answer not found")
    save_feedback(db, msg, body)
