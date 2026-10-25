"""Turn retrieved chunks into an answer with sources.

- extractive (default, offline): the sentences from the top chunks that best match the question, each with its source.
- llm: an OpenAI-compatible chat model (Groq by default) writes the answer from the numbered sources only. Its reply
  must cite source numbers that were actually given to it; otherwise the extractive answer is used instead.
If retrieval abstains, no model is called and the user is pointed to a human.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field

from .embeddings import tokens
from .retriever import Hit

FALLBACK = "I could not find this in the Placement Cell help centre. Please write to placements@geu.example.edu."

SYSTEM = """You are the support assistant of {who}.
Answer ONLY from the numbered sources. If they do not contain the answer, say you could not find it.
Be brief (at most 3 sentences). Reply with JSON only: {"answer": "...", "sources": [numbers you used]}"""


@dataclass
class Answer:
    text: str
    sources: list[str] = field(default_factory=list)  # e.g. "06-withdrawing#when-you-can-withdraw"
    abstained: bool = False
    mode: str = "extractive"
    note: str = ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if s.strip()]


def extractive(question: str, hits: list[Hit], max_sentences: int = 2, top_chunks: int = 3, idf: dict | None = None) -> Answer:
    """Pick the sentences that share the most *informative* words with the question: each shared word counts by its
    IDF, so a rare word like 'closes' outweighs a common one like 'registration'."""
    q = set(tokens(question))
    idf = idf or {}
    scored = []
    for rank, h in enumerate(hits[:top_chunks]):
        for s in _sentences(h.chunk.text):
            overlap = sum(idf.get(t, 1.0) for t in q & set(tokens(s)))
            scored.append((round(overlap, 6), -rank, s, h.chunk.source))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    picked = [x for x in scored if x[0] > 0][:max_sentences] or scored[:1]
    text = " ".join(s for _, _, s, _ in picked)
    sources = list(dict.fromkeys(src for *_, src in picked))
    return Answer(text, sources)


def llm_available() -> bool:
    return bool(os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY"))


def llm(question: str, hits: list[Hit], top_chunks: int = 4, idf: dict | None = None, who: str = "a university Placement Cell") -> Answer:
    key = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
    base = (os.environ.get("LLM_BASE_URL") or "https://api.groq.com/openai/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL") or "llama-3.3-70b-versatile"
    ctx = hits[:top_chunks]
    numbered = "\n\n".join(f"[{i}] ({h.chunk.title} > {h.chunk.section}) {h.chunk.text}" for i, h in enumerate(ctx, 1))
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM.replace("{who}", who)}, {"role": "user", "content": f"Sources:\n{numbered}\n\nQuestion: {question}"}],
        }
    ).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(json.loads(r.read())["choices"][0]["message"]["content"])
        nums = [int(n) for n in out.get("sources", [])]
        text = str(out.get("answer", "")).strip()
        if not text or not nums or any(n < 1 or n > len(ctx) for n in nums):
            raise ValueError("reply did not cite the given sources")
        return Answer(text, list(dict.fromkeys(ctx[n - 1].chunk.source for n in nums)), mode="llm")
    except Exception as e:  # noqa: BLE001 - any LLM problem -> the grounded extractive answer
        a = extractive(question, hits, idf=idf)
        a.note = f"llm unavailable or rejected ({type(e).__name__}); extractive answer used"
        return a


def answer(
    question: str,
    hits: list[Hit],
    abstain: bool,
    use_llm: bool = False,
    idf: dict | None = None,
    fallback: str = FALLBACK,
    who: str = "a university Placement Cell",
) -> Answer:
    """fallback / who: each knowledge base sets its own "contact a human" message and the team the assistant speaks for."""
    if abstain:
        return Answer(fallback, abstained=True, mode="abstain")
    return llm(question, hits, idf=idf, who=who) if use_llm and llm_available() else extractive(question, hits, idf=idf)
