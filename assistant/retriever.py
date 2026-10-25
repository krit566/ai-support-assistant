"""Retrieval: BM25 (exact words), dense vectors (meaning), and a hybrid of both by Reciprocal Rank Fusion.

The retriever also decides when NOT to answer: if even the best chunk is a weak match, the question is probably not
covered by the help centre and the assistant says so instead of guessing.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .chunking import Chunk
from .embeddings import tokens


class BM25:
    """Okapi BM25. k1 limits how much repeating a word helps; b corrects for long chunks."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(docs), 1)
        n = len(docs)
        df = Counter(t for d in docs for t in set(d))
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, q: list[str]) -> np.ndarray:
        out = np.zeros(len(self.tf))
        for i, tf in enumerate(self.tf):
            norm = self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
            out[i] = sum(self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm) for t in q if t in tf)
        return out


@dataclass
class Hit:
    chunk: Chunk
    score: float  # fused score (hybrid) or raw score (single method)
    dense: float  # cosine similarity of this chunk to the question
    bm25: float


class Retriever:
    def __init__(self, chunks: list[Chunk], embedder, rrf_k: int = 60):
        self.chunks = chunks
        texts = [c.for_index() for c in chunks]
        self.bm25 = BM25([tokens(t) for t in texts])
        self.embed = embedder
        self.vecs = embedder(texts)
        self.rrf_k = rrf_k

    def _scores(self, question: str) -> tuple[np.ndarray, np.ndarray]:
        return self.bm25.scores(tokens(question)), self.vecs @ self.embed([question])[0]

    def search(self, question: str, k: int = 5, method: str = "hybrid") -> list[Hit]:
        sparse, dense = self._scores(question)
        if method == "bm25":
            order = np.argsort(-sparse, kind="stable")
            fused = sparse
        elif method == "dense":
            order = np.argsort(-dense, kind="stable")
            fused = dense
        else:
            r_s = np.empty(len(sparse), int)
            r_s[np.argsort(-sparse, kind="stable")] = np.arange(1, len(sparse) + 1)
            r_d = np.empty(len(dense), int)
            r_d[np.argsort(-dense, kind="stable")] = np.arange(1, len(dense) + 1)
            fused = 1 / (self.rrf_k + r_s) + 1 / (self.rrf_k + r_d)
            order = np.argsort(-fused, kind="stable")
        return [Hit(self.chunks[i], float(fused[i]), float(dense[i]), float(sparse[i])) for i in order[:k]]

    def docs_ranked(self, question: str, k: int = 5, method: str = "hybrid") -> list[str]:
        """Distinct articles in rank order (several chunks can come from one article)."""
        seen: list[str] = []
        for h in self.search(question, k=4 * k, method=method):
            if h.chunk.doc not in seen:
                seen.append(h.chunk.doc)
            if len(seen) == k:
                break
        return seen


def should_abstain(hits: list[Hit], min_dense: float, min_bm25: float) -> bool:
    """Weak on BOTH signals -> not covered. Thresholds are chosen on the dev split only (eval/run_eval.py)."""
    if not hits:
        return True
    top = hits[0]
    return top.dense < min_dense and top.bm25 < min_bm25
