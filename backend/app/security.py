"""Passwords (bcrypt), sessions (JWT) and public API keys (random, stored as SHA-256)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import KnowledgeBase, User


def hash_password(pw: str) -> str:
    # bcrypt is deliberately slow and salted, so a leaked table does not reveal passwords quickly
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode()[:72], hashed.encode())


def make_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_minutes)
    # only ids go in the token; the role is re-read from the database on every request, so a demotion is immediate
    return jwt.encode({"sub": str(user.id), "ws": user.workspace_id, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "sign in required")
    try:
        claims = jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"])  # pinning the algorithm blocks "alg: none"
    except jwt.PyJWTError:
        raise HTTPException(401, "session expired or invalid") from None
    user = db.get(User, int(claims["sub"]))
    if user is None:
        raise HTTPException(401, "user no longer exists")
    request.state.user_id = user.id
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "admins only")
    return user


def kb_for(db: Session, user: User, kb_id: int) -> KnowledgeBase:
    """The knowledge base, only if it belongs to the caller's workspace. Another team's id gives 404, not 403,
    so ids cannot be probed to learn what exists."""
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None or kb.workspace_id != user.workspace_id:
        raise HTTPException(404, "knowledge base not found")
    return kb


def new_api_key() -> tuple[str, str]:
    key = "hd_" + secrets.token_urlsafe(24)
    return key, hash_key(key)


def hash_key(key: str) -> str:
    # API keys are long and random, so a fast hash is enough (no need for bcrypt's slowness)
    return hashlib.sha256(key.encode()).hexdigest()


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
