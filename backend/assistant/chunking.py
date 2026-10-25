"""Split markdown articles into retrievable chunks: one chunk per '## section', long sections split with overlap.

Each chunk keeps where it came from (article file, title, section), which becomes the citation shown to the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_WORDS = 120
OVERLAP = 30


@dataclass(frozen=True)
class Chunk:
    doc: str  # file stem, e.g. "06-withdrawing"
    title: str  # article title
    section: str  # section heading
    text: str

    @property
    def source(self) -> str:
        return f"{self.doc}#{re.sub(r'[^a-z0-9]+', '-', self.section.lower()).strip('-')}"

    def for_index(self) -> str:
        """Title and section are part of what gets embedded: they carry a lot of meaning in few words."""
        return f"{self.title}. {self.section}. {self.text}"


def _split_words(text: str) -> list[str]:
    words = text.split()
    if len(words) <= MAX_WORDS:
        return [text]
    parts, step = [], MAX_WORDS - OVERLAP
    for start in range(0, len(words), step):
        parts.append(" ".join(words[start : start + MAX_WORDS]))
        if start + MAX_WORDS >= len(words):
            break
    return parts


def chunk_markdown(doc: str, text: str) -> list[Chunk]:
    title_m = re.search(r"^#\s+(.+)$", text, re.M)
    title = title_m.group(1).strip() if title_m else doc
    heads = list(re.finditer(r"^##\s+(.+)$", text, re.M))
    if not heads:  # a markdown file without "## " sections is chunked like plain text
        body = text[title_m.end() :] if title_m else text
        return chunk_text(doc, title, body)
    chunks = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = " ".join(text[h.end() : end].split())
        for part in _split_words(body):
            if part:
                chunks.append(Chunk(doc, title, h.group(1).strip(), part))
    return chunks


def chunk_text(doc: str, title: str, text: str, label: str = "Part") -> list[Chunk]:
    """Plain text: paragraphs are packed into sections of up to MAX_WORDS words, so a section never cuts a paragraph
    unless the paragraph alone is too long (then it is split with overlap like a long markdown section)."""
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    sections: list[str] = []
    current: list[str] = []
    for para in paragraphs:
        if current and len(" ".join(current + [para]).split()) > MAX_WORDS:
            sections.append(" ".join(current))
            current = []
        current.append(para)
    if current:
        sections.append(" ".join(current))
    chunks = []
    for i, body in enumerate(sections, 1):
        for part in _split_words(body):
            chunks.append(Chunk(doc, title, f"{label} {i}", part))
    return chunks


def chunk_pages(doc: str, title: str, pages: list[str]) -> list[Chunk]:
    """PDF: one section per page ("Page 3"), so a citation tells the reader where to look in the original file."""
    chunks = []
    for n, page in enumerate(pages, 1):
        body = " ".join(page.split())
        for part in _split_words(body):
            if part:
                chunks.append(Chunk(doc, title, f"Page {n}", part))
    return chunks


def load_corpus(directory: Path) -> list[Chunk]:
    out: list[Chunk] = []
    for p in sorted(directory.glob("*.md")):
        out.extend(chunk_markdown(p.stem, p.read_text(encoding="utf-8")))
    if not out:
        raise FileNotFoundError(f"no markdown articles in {directory}")
    return out
