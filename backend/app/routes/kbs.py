"""Knowledge bases, their documents (upload, versions, re-index, delete) and public API keys."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas
from ..config import settings
from ..db import get_session
from ..index import cache, vectors_to_store
from ..ingest import IngestError, chunks_for, parse
from ..models import ApiKey, Chunk, Document, KnowledgeBase, Message, User, now
from ..security import current_user, kb_for, new_api_key, require_admin

router = APIRouter(prefix="/api", tags=["knowledge bases"])


def _bump(db: Session, kb: KnowledgeBase) -> None:
    """Mark the search index stale. Incremented in SQL (not kb.index_version + 1 in Python), so two concurrent
    uploads both count, and committed together with the document change."""
    db.execute(
        update(KnowledgeBase).where(KnowledgeBase.id == kb.id).values(index_version=KnowledgeBase.index_version + 1),
        execution_options={"synchronize_session": "fetch"},
    )


def _kb_out(db: Session, kb: KnowledgeBase) -> schemas.KbOut:
    docs, chunks = db.execute(select(func.count(Document.id), func.coalesce(func.sum(Document.chunk_count), 0)).where(Document.kb_id == kb.id)).one()
    week = datetime.now(timezone.utc) - timedelta(days=7)
    q7 = db.scalar(select(func.count()).where(Message.kb_id == kb.id, Message.role == "user", Message.created_at >= week))
    fields = {k: getattr(kb, k) for k in ("id", "name", "slug", "description", "team_name", "fallback_message", "created_at")}
    return schemas.KbOut(**fields, document_count=docs, chunk_count=int(chunks), questions_7d=q7 or 0)


# ---------------------------------------------------------------- knowledge bases


@router.get("/kbs", response_model=list[schemas.KbOut])
def list_kbs(user: User = Depends(current_user), db: Session = Depends(get_session)):
    kbs = db.scalars(select(KnowledgeBase).where(KnowledgeBase.workspace_id == user.workspace_id).order_by(KnowledgeBase.id)).all()
    return [_kb_out(db, kb) for kb in kbs]


@router.post("/kbs", response_model=schemas.KbOut, status_code=201)
def create_kb(body: schemas.KbIn, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    kb = KnowledgeBase(workspace_id=admin.workspace_id, **body.model_dump())
    db.add(kb)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "this address (slug) is already taken") from None
    return _kb_out(db, kb)


@router.get("/kbs/{kb_id}", response_model=schemas.KbOut)
def get_kb(kb_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _kb_out(db, kb_for(db, user, kb_id))


@router.patch("/kbs/{kb_id}", response_model=schemas.KbOut)
def update_kb(kb_id: int, body: schemas.KbUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    kb = kb_for(db, admin, kb_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(kb, k, v)
    db.commit()
    return _kb_out(db, kb)


@router.delete("/kbs/{kb_id}", status_code=204)
def delete_kb(kb_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    kb = kb_for(db, admin, kb_id)
    db.delete(kb)  # documents, chunks, keys and conversations go with it (ON DELETE CASCADE)
    db.commit()
    cache.drop(kb_id)
    return Response(status_code=204)


@router.get("/kbs/{kb_id}/settings")
def kb_settings(kb_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)):
    """Read-only facts about how this knowledge base answers, shown on the Settings page."""
    kb = kb_for(db, user, kb_id)
    idx = cache.get(db, kb)
    return {
        "embedder": idx.embedder_name,
        "retrieval": "hybrid: BM25 + embeddings, Reciprocal Rank Fusion (k=60)",
        "thresholds": idx.thresholds,
        "thresholds_source": "chosen on the dev split of the placement-cell evaluation set (eval/run_eval.py); a starting point for other knowledge bases",
        "llm_answers": settings.use_llm,
        "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
        "public_rate_default": settings.public_rate_per_minute,
    }


# ---------------------------------------------------------------- documents


@router.get("/kbs/{kb_id}/documents", response_model=list[schemas.DocumentOut])
def list_documents(kb_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)):
    kb_for(db, user, kb_id)
    return db.scalars(select(Document).where(Document.kb_id == kb_id).order_by(Document.filename)).all()


def _store_chunks(db: Session, doc: Document) -> None:
    """(Re)build a document's chunks from its stored text."""
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    parts = chunks_for(doc.doc_key, doc.title, doc.kind, doc.text)
    vecs, emb_name = vectors_to_store([c.for_index() for c in parts])
    for i, c in enumerate(parts):
        db.add(Chunk(document_id=doc.id, kb_id=doc.kb_id, ordinal=i, section=c.section[:300], text=c.text, embedding=vecs[i] if vecs else None, embedder=emb_name))
    doc.chunk_count = len(parts)


@router.post("/kbs/{kb_id}/documents", response_model=schemas.DocumentOut, status_code=201)
async def upload(kb_id: int, response: Response, file: UploadFile = File(...), admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    kb = kb_for(db, admin, kb_id)
    data = await file.read(settings.max_upload_bytes + 1)  # read one byte past the limit to detect oversize files
    try:
        parsed = parse(file.filename or "upload.txt", data, settings.max_upload_bytes)
    except IngestError as e:
        raise HTTPException(e.status, str(e)) from None

    doc = db.scalar(select(Document).where(Document.kb_id == kb.id, Document.filename == parsed.filename).with_for_update())
    if doc is not None:
        if doc.sha256 == parsed.sha256:
            response.status_code = 200  # same file again: nothing to do
            return doc
        doc.version += 1  # a new version replaces the old chunks
        doc.title, doc.kind, doc.text, doc.size_bytes, doc.sha256, doc.updated_at = parsed.title, parsed.kind, parsed.text, parsed.size, parsed.sha256, now()
        response.status_code = 200
    else:
        doc = Document(
            kb_id=kb.id, filename=parsed.filename, doc_key=parsed.doc_key, title=parsed.title, kind=parsed.kind,
            size_bytes=parsed.size, sha256=parsed.sha256, text=parsed.text, uploaded_by=admin.id,
        )  # fmt: skip
        db.add(doc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"another document already uses the id '{parsed.doc_key}'; rename the file") from None
    _store_chunks(db, doc)
    if doc.chunk_count == 0:
        db.rollback()
        raise HTTPException(422, "no text could be read from this file")
    _bump(db, kb)
    db.commit()
    db.refresh(doc)
    return doc


def _doc(db: Session, user: User, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    kb_for(db, user, doc.kb_id)  # 404 if it belongs to another workspace
    return doc


@router.get("/documents/{doc_id}/chunks", response_model=list[schemas.ChunkOut])
def document_chunks(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_session)):
    return _doc(db, user, doc_id).chunks


@router.post("/documents/{doc_id}/reindex", response_model=schemas.DocumentOut)
def reindex(doc_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    doc = _doc(db, admin, doc_id)
    _store_chunks(db, doc)
    _bump(db, doc.kb)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    doc = _doc(db, admin, doc_id)
    kb = doc.kb
    db.delete(doc)
    _bump(db, kb)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- public API keys


@router.get("/kbs/{kb_id}/keys", response_model=list[schemas.KeyOut])
def list_keys(kb_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    kb_for(db, admin, kb_id)
    return db.scalars(select(ApiKey).where(ApiKey.kb_id == kb_id).order_by(ApiKey.id)).all()


@router.post("/kbs/{kb_id}/keys", response_model=schemas.KeyCreated, status_code=201)
def create_key(kb_id: int, body: schemas.KeyIn, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    kb_for(db, admin, kb_id)
    key, digest = new_api_key()
    k = ApiKey(kb_id=kb_id, name=body.name, prefix=key[:10], key_hash=digest, rate_per_minute=body.rate_per_minute)
    db.add(k)
    db.commit()
    return schemas.KeyCreated(**schemas.KeyOut.model_validate(k).model_dump(), key=key)


@router.delete("/kbs/{kb_id}/keys/{key_id}", response_model=schemas.KeyOut)
def revoke_key(kb_id: int, key_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_session)):
    kb_for(db, admin, kb_id)
    k = db.get(ApiKey, key_id)
    if k is None or k.kb_id != kb_id:
        raise HTTPException(404, "key not found")
    k.revoked_at = k.revoked_at or now()  # kept (not deleted) so old conversations still show which key they came from
    db.commit()
    return k
