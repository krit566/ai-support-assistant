"""Request and response shapes. Validation here means bad input is rejected (422) before any database work."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if not EMAIL.match(v):
        raise ValueError("not a valid email address")
    return v


class Signup(BaseModel):
    workspace: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _email(v)


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class NewUser(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["admin", "agent"] = "agent"

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _email(v)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: str


class Session(BaseModel):
    token: str
    user: UserOut
    workspace: str


class KbIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    description: str = Field(default="", max_length=500)
    team_name: str = Field(default="the support team", min_length=2, max_length=100)
    fallback_message: str = Field(default="I could not find this in our help centre. Please contact the support team.", min_length=10, max_length=500)


class KbUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    team_name: str | None = Field(default=None, min_length=2, max_length=100)
    fallback_message: str | None = Field(default=None, min_length=10, max_length=500)


class KbOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    description: str
    team_name: str
    fallback_message: str
    created_at: datetime
    document_count: int = 0
    chunk_count: int = 0
    questions_7d: int = 0


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    doc_key: str
    title: str
    kind: str
    size_bytes: int
    version: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ordinal: int
    section: str
    text: str


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    conversation_id: int | None = None


class Passage(BaseModel):
    source: str
    title: str
    section: str
    text: str
    document_id: int | None = None
    chunk_id: int | None = None


class AnswerOut(BaseModel):
    conversation_id: int
    message_id: int
    text: str
    abstained: bool
    mode: str
    sources: list[Passage]
    note: str = ""


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    text: str
    sources: list[Passage] | None = None
    abstained: bool
    mode: str | None
    created_at: datetime
    rating: int | None = None


class ConversationOut(BaseModel):
    id: int
    channel: str
    is_demo: bool
    created_at: datetime
    first_question: str
    messages: int
    refused: int
    rating_down: int


class FeedbackIn(BaseModel):
    rating: Literal[1, -1]
    comment: str = Field(default="", max_length=1000)


class KeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    rate_per_minute: int = Field(default=20, ge=1, le=600)


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    prefix: str
    rate_per_minute: int
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class KeyCreated(KeyOut):
    key: str  # shown once


class PublicKb(BaseModel):
    name: str
    description: str
    team_name: str


class PublicAsk(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    conversation_id: int | None = None
