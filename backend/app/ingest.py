"""Uploaded file -> checked -> text -> chunks.

Checks happen before any parsing: size limit (413), allowed extension (415), and the content must match the
extension (a ".pdf" must start with %PDF-, text must be valid UTF-8), so a renamed binary is rejected (415).
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import PurePath

from assistant.chunking import Chunk, chunk_markdown, chunk_pages, chunk_text

KINDS = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown", ".txt": "text"}
PAGE_BREAK = "\f"


class IngestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Parsed:
    filename: str
    doc_key: str
    title: str
    kind: str
    text: str  # PDF pages joined with \f
    sha256: str
    size: int


def doc_key_for(filename: str) -> str:
    """"06-withdrawing.md" -> "06-withdrawing": the id that appears in citations."""
    stem = PurePath(filename).stem.lower()
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:120] or "document"


def safe_name(filename: str) -> str:
    # keep only the last path part and ordinary characters: never trust a client-supplied path
    name = PurePath(filename.replace("\\", "/")).name
    return re.sub(r"[^\w.\- ]+", "_", name)[:200] or "upload.txt"


def parse(filename: str, data: bytes, max_bytes: int) -> Parsed:
    name = safe_name(filename)
    if len(data) > max_bytes:
        raise IngestError(413, f"file is larger than {max_bytes // (1024 * 1024)} MB")
    if not data:
        raise IngestError(422, "file is empty")
    kind = KINDS.get(PurePath(name).suffix.lower())
    if kind is None:
        raise IngestError(415, "only PDF, Markdown (.md) and text (.txt) files are supported")

    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            raise IngestError(415, "this file is not a valid PDF")
        text, title = _pdf_text(data)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise IngestError(415, "text files must be UTF-8") from None
        if "\x00" in text:
            raise IngestError(415, "this looks like a binary file, not text")
        m = re.search(r"^#\s+(.+)$", text, re.M) if kind == "markdown" else None
        title = m.group(1).strip() if m else ""

    if not text.replace(PAGE_BREAK, "").strip():
        raise IngestError(422, "no text could be read from this file (a scanned PDF needs OCR first)")
    return Parsed(name, doc_key_for(name), (title or PurePath(name).stem)[:300], kind, text, hashlib.sha256(data).hexdigest(), len(data))


def _pdf_text(data: bytes) -> tuple[str, str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
        title = (reader.metadata.title if reader.metadata else None) or ""
    except (PdfReadError, ValueError, KeyError) as e:
        raise IngestError(422, f"could not read this PDF ({type(e).__name__})") from None
    return PAGE_BREAK.join(pages), str(title)


def chunks_for(doc_key: str, title: str, kind: str, text: str) -> list[Chunk]:
    """Same chunking rules as the evaluated engine: markdown by "## " sections, PDFs by page, text by paragraphs."""
    if kind == "markdown":
        return chunk_markdown(doc_key, text if text.lstrip().startswith("#") else f"# {title}\n\n{text}")
    if kind == "pdf":
        return chunk_pages(doc_key, title, text.split(PAGE_BREAK))
    return chunk_text(doc_key, title, text)
