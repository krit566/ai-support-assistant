"""Small pure-function tests (no database)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.index import rare_word_weight, reference_chunks, scaled_thresholds  # noqa: E402
from app.ingest import IngestError, chunks_for, doc_key_for, parse, safe_name  # noqa: E402
from app.ratelimit import SlidingWindow  # noqa: E402


def test_threshold_is_unchanged_on_the_evaluated_corpus_and_scales_elsewhere():
    base = {"min_dense": 0.98, "min_bm25": 3.5}
    assert scaled_thresholds(base, reference_chunks()) == base
    small = scaled_thresholds(base, 2)["min_bm25"]
    big = scaled_thresholds(base, 5000)["min_bm25"]
    assert small < 3.5 < big
    # one rare word in a 2-chunk knowledge base clears the scaled bar, just as one rare word does in the big corpus
    assert rare_word_weight(2) >= small


def test_sliding_window_allows_limit_then_blocks_until_the_oldest_request_expires():
    now = [100.0]
    w = SlidingWindow(60, clock=lambda: now[0])
    assert w.allow("k", 2) == (True, 0)
    now[0] = 110
    assert w.allow("k", 2) == (True, 0)
    allowed, retry = w.allow("k", 2)
    assert not allowed and retry == 50  # the first request (t=100) leaves the window at t=160
    assert w.allow("other", 2) == (True, 0)  # keys are counted separately
    now[0] = 160.5
    assert w.allow("k", 2) == (True, 0)


def test_file_names_are_sanitised_and_turned_into_citation_ids():
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("C:\\Users\\x\\Refund Policy.md") == "Refund Policy.md"
    assert doc_key_for("Refund Policy (v2).md") == "refund-policy-v2"


def test_text_is_packed_into_sections_by_paragraph():
    paras = "\n\n".join(f"Paragraph {i} " + "word " * 50 for i in range(5))
    chunks = chunks_for("notes", "Notes", "text", paras)
    assert [c.section for c in chunks] == ["Part 1", "Part 2", "Part 3"]  # two ~52-word paragraphs fit in 120 words
    assert chunks[0].text.startswith("Paragraph 0") and "Paragraph 1" in chunks[0].text


def test_markdown_without_sections_is_still_indexed():
    chunks = chunks_for("faq", "FAQ", "markdown", "# FAQ\n\nWe ship within two days.")
    assert len(chunks) == 1 and chunks[0].title == "FAQ"


def test_parse_reports_the_right_status_codes():
    for name, data, status in [("a.docx", b"PK", 415), ("a.txt", b"x" * 11, 413)]:
        try:
            parse(name, data, max_bytes=10)
        except IngestError as e:
            assert e.status == status
        else:
            raise AssertionError(name)
