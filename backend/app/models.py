"""Tables.

workspace ─┬─ users (admin | agent)
           └─ knowledge_bases ─┬─ documents ── chunks
                               ├─ api_keys (public widget)
                               └─ conversations ── messages ── feedback

Every query that reads a knowledge base filters by the caller's workspace, so one team never sees another's data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10))  # "admin" manages content and keys; "agent" chats and reads analytics
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("role in ('admin', 'agent')", name="ck_user_role"),)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(60), unique=True)  # used by the public chat page: /chat/<slug>
    description: Mapped[str] = mapped_column(Text, default="")
    team_name: Mapped[str] = mapped_column(String(100), default="the support team")  # "You are the assistant of ..."
    fallback_message: Mapped[str] = mapped_column(Text)  # shown when the assistant refuses
    # Bumped in the same transaction as any document change; a cached index with an older version is rebuilt.
    index_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    documents: Mapped[list[Document]] = relationship(back_populates="kb", cascade="all, delete-orphan", passive_deletes=True)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    doc_key: Mapped[str] = mapped_column(String(120))  # stable id used in citations, e.g. "06-withdrawing"
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(10))  # pdf | markdown | text
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)  # +1 every time a file with the same name is uploaded
    # Extracted text is kept so the document can be re-chunked later without the original file.
    # PDF pages are separated by form feeds (\f) so page numbers survive.
    text: Mapped[str] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    kb: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(cascade="all, delete-orphan", passive_deletes=True, order_by="Chunk.ordinal")
    __table_args__ = (UniqueConstraint("kb_id", "filename", name="uq_document_filename"), UniqueConstraint("kb_id", "doc_key", name="uq_document_key"))


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    # Vectors from embedders that do not depend on the corpus (sbert, api) are stored so they are computed once.
    # LSA is refitted on the whole knowledge base at every rebuild, so its vectors are not stored.
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    embedder: Mapped[str | None] = mapped_column(String(80))


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(12))  # first characters, shown in the UI to tell keys apart
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 of the key; the key itself is shown once
    rate_per_minute: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(10))  # "console" (playground) | "public" (widget)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)  # seeded sample data, labelled in the UI
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    messages: Mapped[list[Message]] = relationship(cascade="all, delete-orphan", passive_deletes=True, order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    # For answers: the passages cited, copied at answer time ({source, title, section, text, document_id}),
    # so an old answer still shows what it was based on after the document changes.
    sources: Mapped[list | None] = mapped_column(JSONB)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str | None] = mapped_column(String(12))  # extractive | llm | abstain
    latency_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    feedback: Mapped[Feedback | None] = relationship(cascade="all, delete-orphan", passive_deletes=True, uselist=False)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), unique=True)
    rating: Mapped[int] = mapped_column(SmallInteger)  # +1 helpful, -1 not helpful
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("rating in (-1, 1)", name="ck_feedback_rating"),)
