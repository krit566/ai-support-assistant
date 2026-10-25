"""Search index per knowledge base, kept in memory and rebuilt when the knowledge base changes.

Why in memory and not pgvector: BM25 needs corpus-wide word statistics and LSA is fitted on the whole corpus, so
both are rebuilt from all chunks anyway. For knowledge bases of a few thousand chunks this takes well under a second.
pgvector would let the database do the vector search for very large collections, but BM25 would still need a
separate full-text index; see the README for the trade-off.

Correctness across several server processes: every document change bumps knowledge_bases.index_version in the
same transaction. Before answering, the cached index's version is compared with the database; a stale one is rebuilt.
"""

from __future__ import annotations

import json
import math
import threading
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.answer import Answer, answer
from assistant.chunking import Chunk as EngineChunk
from assistant.embeddings import TfidfEmbedder, make_embedder
from assistant.retriever import Hit, Retriever, should_abstain

from .config import settings
from .models import Chunk, Document, KnowledgeBase

THRESHOLDS_FILE = Path(__file__).resolve().parent.parent / "eval" / "thresholds.json"
DEFAULT_THRESHOLDS = {"min_dense": 0.2, "min_bm25": 3.0}
MIN_CHUNKS_FOR_LSA = 8  # an SVD on a handful of chunks is meaningless; plain TF-IDF is used below this


def thresholds_for(embedder_name: str) -> dict:
    """The refuse thresholds chosen on the placement-cell DEV split (eval/run_eval.py). For other knowledge bases they
    are a starting point, not a tuned value; the analytics page shows how often the assistant refuses."""
    try:
        saved = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return saved.get(embedder_name) or saved.get("lsa") or DEFAULT_THRESHOLDS


def rare_word_weight(n_chunks: int) -> float:
    """BM25 weight (IDF) of a word that occurs in exactly one of n chunks: log(1 + (n - 0.5) / 1.5)."""
    return math.log(1 + (n_chunks - 0.5) / 1.5)


@lru_cache(maxsize=1)
def reference_chunks() -> int:
    """Size of the corpus the thresholds were tuned on (the placement-cell articles)."""
    from assistant.chunking import load_corpus
    from assistant.core import DOCS

    return len(load_corpus(DOCS))


def scaled_thresholds(base: dict, n_chunks: int) -> dict:
    """BM25 scores grow with corpus size: the same rare word weighs 0.69 in a 2-chunk knowledge base and 3.58 in
    the 53-chunk placement corpus. So the BM25 threshold is kept in units of "one rare word" and converted for each
    knowledge base. For the placement corpus itself the result is exactly the dev-tuned value, so the evaluation
    numbers still describe the product."""
    out = dict(base)
    out["min_bm25"] = base["min_bm25"] / rare_word_weight(reference_chunks()) * rare_word_weight(n_chunks)
    return out


@dataclass
class KbIndex:
    version: int
    retriever: Retriever | None  # None when the knowledge base has no documents yet
    chunk_ids: list[int]
    doc_ids: list[int]
    thresholds: dict
    embedder_name: str

    def search(self, question: str, k: int = 5) -> tuple[list[Hit], list[int]]:
        if self.retriever is None:
            return [], []
        hits = self.retriever.search(question, k=k)
        # map each hit back to its database chunk (positions in the retriever match chunk_ids)
        pos = {id(c): i for i, c in enumerate(self.retriever.chunks)}
        return hits, [pos[id(h.chunk)] for h in hits]


def build(db: Session, kb: KnowledgeBase) -> KbIndex:
    rows = db.execute(
        select(Chunk, Document.title, Document.doc_key)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.kb_id == kb.id)
        .order_by(Document.filename, Chunk.ordinal)  # same order as the file-based engine (sorted file names)
    ).all()
    if not rows:
        return KbIndex(kb.index_version, None, [], [], thresholds_for(settings.embedder), settings.embedder)
    # doc_key gives citation ids like "06-withdrawing#no-show-penalty", the same as the file-based engine
    chunks = [EngineChunk(doc=key, title=title, section=c.section, text=c.text) for c, title, key in rows]
    texts = [c.for_index() for c in chunks]
    if settings.embedder == "lsa" and len(chunks) < MIN_CHUNKS_FOR_LSA:
        emb = TfidfEmbedder(texts)
    else:
        emb = make_embedder(settings.embedder, texts)
    vecs = _stored_vectors([r[0] for r in rows], emb.name)
    retriever = Retriever(chunks, emb, vecs=vecs)
    th = scaled_thresholds(thresholds_for(emb.name), len(chunks))
    return KbIndex(kb.index_version, retriever, [r[0].id for r in rows], [r[0].document_id for r in rows], th, emb.name)


def vectors_to_store(texts: list[str]) -> tuple[list[list[float]] | None, str | None]:
    """At upload time: vectors for embedders that do not depend on the rest of the corpus (sbert, api).
    LSA depends on every chunk in the knowledge base, so it is computed at rebuild time instead."""
    if settings.embedder in ("sbert", "api") and texts:
        emb = make_embedder(settings.embedder, texts)
        return emb(texts).tolist(), emb.name
    return None, None


def _stored_vectors(rows: list[Chunk], name: str) -> np.ndarray | None:
    """Reuse stored vectors only if every chunk has one from this same embedder (LSA never stores any)."""
    if name in ("lsa", "tfidf") or not rows or any(r.embedding is None or r.embedder != name for r in rows):
        return None
    return np.asarray([r.embedding for r in rows], dtype=float)


class IndexCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[int, KbIndex] = {}

    def get(self, db: Session, kb: KnowledgeBase) -> KbIndex:
        with self._lock:
            cached = self._cache.get(kb.id)
            if cached and cached.version == kb.index_version:
                return cached
        fresh = build(db, kb)
        with self._lock:
            self._cache[kb.id] = fresh
        return fresh

    def drop(self, kb_id: int) -> None:
        with self._lock:
            self._cache.pop(kb_id, None)


cache = IndexCache()


@dataclass
class Result:
    answer: Answer
    passages: list[dict]  # what the answer cites: source, title, section, text, document_id, chunk_id


def ask(db: Session, kb: KnowledgeBase, question: str) -> Result:
    question = " ".join(question.split())[:500]
    idx = cache.get(db, kb)
    hits, positions = idx.search(question)
    abstain = should_abstain(hits, **idx.thresholds)
    idf = idx.retriever.bm25.idf if idx.retriever else None
    ans = answer(question, hits, abstain, settings.use_llm, idf=idf, fallback=kb.fallback_message, who=kb.team_name)
    # the answer cites sources by id; attach the exact passage text so the UI can show it next to the answer
    passages = []
    for src in ans.sources:
        for h, p in zip(hits, positions):
            if h.chunk.source == src:
                passages.append(
                    {"source": src, "title": h.chunk.title, "section": h.chunk.section, "text": h.chunk.text, "document_id": idx.doc_ids[p], "chunk_id": idx.chunk_ids[p]}
                )
                break
    return Result(ans, passages)
