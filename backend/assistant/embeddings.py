"""Three interchangeable embedders (texts -> L2-normalised vectors):

- lsa    TF-IDF + truncated SVD, fitted on the corpus. Offline, no download; learns which words occur together.
- sbert  a pretrained sentence-transformers model (pip install sentence-transformers; downloads ~90 MB once).
- api    any OpenAI-compatible /embeddings endpoint (OpenAI, a local Ollama, ...). Key from EMBED_API_KEY.

Pick one with the EMBEDDER environment variable or the --embedder flag. The evaluation reports which one it used.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

STOP = set(
    "a an the and or of to in on for is are be it at by with as from this that if so any can i my me do does "
    "what when how who which will would should you your we our there their was were has have had not no".split()
)


def stem(w: str) -> str:
    """Very light suffix stripping so 'closes'/'closed'/'closing' -> 'clos', 'withdrawing' -> 'withdraw'."""
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list[str]:
    return [stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP and len(t) > 1]


def _norm(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)


class LsaEmbedder:
    name = "lsa"

    def __init__(self, corpus: list[str], dim: int = 64, seed: int = 0):
        self.vec = TfidfVectorizer(tokenizer=tokens, lowercase=False, token_pattern=None, sublinear_tf=True, ngram_range=(1, 2))
        x = self.vec.fit_transform(corpus)
        self.svd = TruncatedSVD(n_components=min(dim, x.shape[0] - 1, x.shape[1] - 1), random_state=seed).fit(x)

    def __call__(self, texts: list[str]) -> np.ndarray:
        return _norm(self.svd.transform(self.vec.transform(texts)))


class TfidfEmbedder:
    """Plain TF-IDF vectors. Used instead of LSA when a knowledge base is too small to fit an SVD (a few chunks)."""

    name = "tfidf"

    def __init__(self, corpus: list[str]):
        self.vec = TfidfVectorizer(tokenizer=tokens, lowercase=False, token_pattern=None, sublinear_tf=True, ngram_range=(1, 2))
        self.vec.fit(corpus)

    def __call__(self, texts: list[str]) -> np.ndarray:
        return _norm(self.vec.transform(texts).toarray())


class SbertEmbedder:
    def __init__(self, model: str | None = None):
        from sentence_transformers import SentenceTransformer  # optional dependency

        self.model_name = model or os.environ.get("SBERT_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.model = SentenceTransformer(self.model_name)
        self.name = f"sbert:{self.model_name.split('/')[-1]}"

    def __call__(self, texts: list[str]) -> np.ndarray:
        return _norm(np.asarray(self.model.encode(texts, batch_size=32, show_progress_bar=False)))


class ApiEmbedder:
    def __init__(self):
        self.base = (os.environ.get("EMBED_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = os.environ.get("EMBED_MODEL") or "text-embedding-3-small"
        self.key = os.environ.get("EMBED_API_KEY") or ""
        self.name = f"api:{self.model}"

    def __call__(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 64):
            body = json.dumps({"model": self.model, "input": texts[i : i + 64]}).encode()
            req = urllib.request.Request(
                self.base + "/embeddings", data=body, headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())["data"]
            out.extend(d["embedding"] for d in sorted(data, key=lambda d: d["index"]))
        return _norm(np.asarray(out, dtype=float))


def make_embedder(kind: str, corpus: list[str]):
    kind = (kind or "lsa").lower()
    if kind == "lsa":
        return LsaEmbedder(corpus)
    if kind == "sbert":
        return SbertEmbedder()
    if kind == "api":
        return ApiEmbedder()
    raise ValueError(f"unknown embedder {kind!r} (use lsa, sbert or api)")
