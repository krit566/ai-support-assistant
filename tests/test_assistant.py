import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import answer as answer_mod  # noqa: E402
from assistant.chunking import MAX_WORDS, chunk_markdown, load_corpus  # noqa: E402
from assistant.core import DOCS, Assistant  # noqa: E402
from assistant.embeddings import stem, tokens  # noqa: E402
from assistant.retriever import BM25, Hit, should_abstain  # noqa: E402


@pytest.fixture(scope="module")
def bot():
    return Assistant()


def test_chunks_follow_sections_and_keep_their_source():
    text = "# Title\n\n## First part\nAlpha beta.\n\n## Second part\nGamma delta."
    chunks = chunk_markdown("07-demo", text)
    assert [c.section for c in chunks] == ["First part", "Second part"]
    assert chunks[1].source == "07-demo#second-part"
    assert chunks[0].for_index().startswith("Title. First part.")


def test_long_sections_are_split_with_overlap():
    words = " ".join(f"w{i}" for i in range(300))
    chunks = chunk_markdown("d", f"# T\n\n## S\n{words}")
    assert len(chunks) > 1
    assert all(len(c.text.split()) <= MAX_WORDS for c in chunks)
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert first[-1] in second  # consecutive chunks share words, so no sentence is cut off from its context


def test_corpus_loads_all_articles():
    chunks = load_corpus(DOCS)
    assert len({c.doc for c in chunks}) == 20


def test_tokens_drop_stopwords_and_stem():
    assert stem("closes") == "clos" and stem("withdrawing") == "withdraw" and stem("is") == "is"
    assert tokens("When does the registration close?") == ["registration", "close"]


def test_bm25_rewards_rare_matching_words():
    bm = BM25([["portal", "fee"], ["portal", "password"], ["portal", "resume"]])
    s = bm.scores(["password"])
    assert s.argmax() == 1 and s[0] == 0


@pytest.mark.parametrize(
    "question,doc",
    [
        ("How long is the password reset link valid?", "16-password-reset"),
        ("Can I withdraw after my interview is scheduled?", "06-withdrawing"),
        ("What is a dream company?", "07-one-offer-policy"),
    ],
)
def test_retrieval_finds_the_right_article(bot, question, doc):
    assert bot.retriever.docs_ranked(question, k=3)[0] == doc


def test_answers_cite_their_sources(bot):
    a = bot.ask("How long is the password reset link valid?")
    assert not a.abstained
    assert "30 minutes" in a.text
    assert a.sources and a.sources[0].startswith("16-password-reset#")


def test_abstains_when_both_signals_are_weak():
    from assistant.chunking import Chunk

    weak = Hit(Chunk("d", "t", "s", "x"), score=0, dense=0.1, bm25=0.5)
    strong_words = Hit(Chunk("d", "t", "s", "x"), score=0, dense=0.1, bm25=9.0)
    assert should_abstain([weak], min_dense=0.5, min_bm25=3)
    assert not should_abstain([strong_words], min_dense=0.5, min_bm25=3)
    assert should_abstain([], min_dense=0.5, min_bm25=3)


def test_abstained_answer_points_to_a_human(bot):
    a = answer_mod.answer("anything", [], abstain=True)
    assert a.abstained and "placements@" in a.text and a.sources == []


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_llm(reply: dict):
    body = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
    return lambda req, timeout=None: _FakeResponse(body)


def test_llm_answer_must_cite_sources_it_was_given(bot, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    hits = bot.retriever.search("How long is the password reset link valid?", k=4)
    monkeypatch.setattr(answer_mod.urllib.request, "urlopen", _fake_llm({"answer": "It is valid for 30 minutes.", "sources": [1]}))
    good = answer_mod.answer("q", hits, abstain=False, use_llm=True)
    assert good.mode == "llm" and good.sources == [hits[0].chunk.source]

    # a made-up source number is rejected and the grounded extractive answer is used instead
    monkeypatch.setattr(answer_mod.urllib.request, "urlopen", _fake_llm({"answer": "Valid for 2 days.", "sources": [9]}))
    bad = answer_mod.answer("How long is the password reset link valid?", hits, abstain=False, use_llm=True)
    assert bad.mode == "extractive" and "rejected" in bad.note
    assert "2 days" not in bad.text


def test_http_api():
    from fastapi.testclient import TestClient

    from assistant.api import app

    c = TestClient(app)
    r = c.post("/ask", json={"question": "How long is the password reset link valid?"})
    assert r.status_code == 200 and r.json()["sources"]
    assert c.post("/ask", json={"question": "?"}).status_code == 422
    assert c.get("/health").json()["chunks"] > 0


def test_web_page_is_served():
    from fastapi.testclient import TestClient

    from assistant.api import app

    r = TestClient(app).get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert 'fetch("/ask"' in r.text and 'aria-live="polite"' in r.text


def test_http_api_observability():
    from fastapi.testclient import TestClient

    from assistant.api import app

    c = TestClient(app)
    before = c.get("/metrics").json()["questions"]
    r = c.post("/ask", json={"question": "What is the hostel curfew?"}, headers={"X-Request-ID": "req-42"})
    assert r.headers["X-Request-ID"] == "req-42"
    m = c.get("/metrics").json()
    assert m["questions"] == before + 1
    assert set(m["outcomes"]) <= {"refused", "answered_extractive", "answered_llm"}
    assert m["latency_ms"]["p95"] >= m["latency_ms"]["p50"] >= 0
