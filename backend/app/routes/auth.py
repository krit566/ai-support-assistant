"""Sign up (creates a workspace and its first admin), sign in, and workspace members."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_session
from ..models import User, Workspace
from ..security import check_password, current_user, hash_password, make_token, require_admin

router = APIRouter(prefix="/api", tags=["auth"])

# Checked when the email is unknown, so a wrong email takes as long as a wrong password (no account probing by timing).
_DUMMY_HASH = hash_password("not-a-real-password")


def _session(db: Session, user: User) -> schemas.Session:
    ws = db.get(Workspace, user.workspace_id)
    return schemas.Session(token=make_token(user), user=schemas.UserOut.model_validate(user), workspace=ws.name if ws else "")


@router.post("/auth/signup", response_model=schemas.Session, status_code=201)
def signup(body: schemas.Signup, db: Session = Depends(get_session)):
    ws = Workspace(name=body.workspace.strip())
    db.add(ws)
    db.flush()
    user = User(workspace_id=ws.id, email=body.email, name=body.name.strip(), password_hash=hash_password(body.password), role="admin")
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "an account with this email already exists") from None
    return _session(db, user)


@router.post("/auth/login", response_model=schemas.Session)
def login(body: schemas.Login, db: Session = Depends(get_session)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    ok = check_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(401, "wrong email or password")  # same message either way
    return _session(db, user)


@router.get("/auth/me", response_model=schemas.Session)
def me(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _session(db, user)


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return db.scalars(select(User).where(User.workspace_id == user.workspace_id).order_by(User.id)).all()


@router.post("/users", response_model=schemas.UserOut, status_code=201)
def add_user(body: schemas.NewUser, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    u = User(workspace_id=admin.workspace_id, email=body.email, name=body.name.strip(), password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "an account with this email already exists") from None
    return u
