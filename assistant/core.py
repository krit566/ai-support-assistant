"""The assistant: load articles -> chunk -> index -> for each question: retrieve, decide, answer with sources."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from .answer import Answer, answer
from .chunking import load_corpus
from .embeddings import make_embedder
from .retriever import Retriever, should_abstain

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "docs"
THRESHOLDS = ROOT / "eval" / "thresholds.json"  # written by eval/run_eval.py from the dev split
DEFAULT_THRESHOLDS = {"min_dense": 0.2, "min_bm25": 3.0}


class Assistant:
    def __init__(self, docs: Path = DOCS, embedder: str | None = None, method: str = "hybrid", use_llm: bool = False):
        self.chunks = load_corpus(docs)
        self.embedder = make_embedder(embedder or os.environ.get("EMBEDDER", "lsa"), [c.for_index() for c in self.chunks])
        self.retriever = Retriever(self.chunks, self.embedder)
        self.method, self.use_llm = method, use_llm
        self.thresholds = self._load_thresholds()

    def _load_thresholds(self) -> dict:
        try:
            saved = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
            return saved.get(self.embedder.name, DEFAULT_THRESHOLDS)
        except (OSError, ValueError):
            return DEFAULT_THRESHOLDS

    def ask(self, question: str, k: int = 5) -> Answer:
        question = " ".join(question.split())[:500]
        hits = self.retriever.search(question, k=k, method=self.method)
        abstain = should_abstain(hits, **self.thresholds)
        return answer(question, hits, abstain, self.use_llm, idf=self.retriever.bm25.idf)

    def ask_dict(self, question: str) -> dict:
        return asdict(self.ask(question))
