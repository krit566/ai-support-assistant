"""HelpDesk AI product tests: accounts, uploads, answers with citations, isolation, feedback, analytics, public keys.

All against a real PostgreSQL (see conftest.py).
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "data" / "docs"
PW = "correct-horse-battery"

REFUND_MD = b"""# Refund policy

## How to request a refund
Open the Orders page and choose Request refund within 14 days of delivery.

## When refunds are paid
Approved refunds reach the original payment method within 5 working days.
"""


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of text per page (Helvetica), built by hand so tests need no PDF library."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", ""]
    kids = []
    for i, text in enumerate(pages):
        page_no, content_no = 3 + 2 * i, 4 + 2 * i
        kids.append(f"{page_no} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_no} 0 R /Resources << /Font << /F1 {3 + 2 * len(pages)} 0 R >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for n, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def signup(client, email="admin@a.example", workspace="Team A") -> dict:
    r = client.post("/api/auth/signup", json={"workspace": workspace, "name": "Admin", "email": email, "password": PW})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def new_kb(client, h, slug="shop-help", **extra) -> int:
    body = {"name": "Shop help", "slug": slug, "fallback_message": "Sorry, I could not find that. Email help@shop.example.", **extra}
    r = client.post("/api/kbs", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, h, kb, name, data, status=201):
    r = client.post(f"/api/kbs/{kb}/documents", files={"file": (name, data)}, headers=h)
    assert r.status_code == status, r.text
    return r.json()


def ask(client, h, kb, q, **extra):
    r = client.post(f"/api/kbs/{kb}/ask", json={"question": q, **extra}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- accounts


def test_signup_login_and_generic_login_errors(client):
    signup(client)
    ok = client.post("/api/auth/login", json={"email": "ADMIN@a.example", "password": PW})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "admin" and ok.json()["workspace"] == "Team A"
    wrong_pw = client.post("/api/auth/login", json={"email": "admin@a.example", "password": "nope-nope-nope"})
    no_user = client.post("/api/auth/login", json={"email": "ghost@a.example", "password": "nope-nope-nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()  # nothing reveals which emails have accounts
    assert client.post("/api/auth/signup", json={"workspace": "Team X", "name": "Yan", "email": "admin@a.example", "password": PW}).status_code == 409
    assert client.post("/api/auth/signup", json={"workspace": "Team X", "name": "Yan", "email": "z@a.example", "password": "short"}).status_code == 422
    assert client.get("/api/kbs").status_code == 401
    assert client.get("/api/kbs", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


# ---------------------------------------------------------------- uploads and answers


def test_markdown_upload_is_chunked_and_answers_cite_it(client):
    h = signup(client)
    kb = new_kb(client, h)
    doc = upload(client, h, kb, "refund-policy.md", REFUND_MD)
    assert doc["doc_key"] == "refund-policy" and doc["title"] == "Refund policy" and doc["chunk_count"] == 2
    chunks = client.get(f"/api/documents/{doc['id']}/chunks", headers=h).json()
    assert [c["section"] for c in chunks] == ["How to request a refund", "When refunds are paid"]

    a = ask(client, h, kb, "How many working days until my refund is paid?")
    assert not a["abstained"] and "5 working days" in a["text"]
    src = a["sources"][0]
    assert src["source"] == "refund-policy#when-refunds-are-paid" and src["document_id"] == doc["id"]
    assert src["text"] in [c["text"] for c in chunks]  # the passage shown is exactly a stored chunk


def test_pdf_and_text_uploads(client):
    h = signup(client)
    kb = new_kb(client, h)
    pdf = upload(client, h, kb, "warranty.pdf", make_pdf(["Warranty covers manufacturing defects.", "Warranty claims need the original invoice number."]))
    assert pdf["kind"] == "pdf" and pdf["chunk_count"] == 2
    assert [c["section"] for c in client.get(f"/api/documents/{pdf['id']}/chunks", headers=h).json()] == ["Page 1", "Page 2"]
    txt = upload(client, h, kb, "shipping notes.txt", b"Orders ship within two days.\n\nInternational orders take ten days to arrive.")
    assert txt["kind"] == "text" and txt["doc_key"] == "shipping-notes"

    a = ask(client, h, kb, "What do I need for a warranty claim?")
    assert a["sources"][0]["source"] == "warranty#page-2" and "invoice" in a["text"]


@pytest.mark.parametrize(
    "name,data,status",
    [
        ("virus.exe", b"MZ\x90\x00", 415),
        ("fake.pdf", b"this is not a pdf", 415),
        ("binary.txt", b"\xff\xfe\x00\x00\x81", 415),
        ("nul.md", b"# T\x00\x00", 415),
        ("empty.txt", b"", 422),
        ("blank.txt", b"   \n\n  ", 422),
        ("broken.pdf", b"%PDF-1.4 garbage", 422),
    ],
)
def test_bad_uploads_are_rejected(client, name, data, status):
    h = signup(client)
    kb = new_kb(client, h)
    upload(client, h, kb, name, data, status=status)
    assert client.get(f"/api/kbs/{kb}/documents", headers=h).json() == []


def test_oversize_upload_is_rejected(client, monkeypatch):
    from app.routes import kbs

    monkeypatch.setattr(kbs, "settings", replace(kbs.settings, max_upload_bytes=1024))
    h = signup(client)
    kb = new_kb(client, h)
    upload(client, h, kb, "big.txt", b"word " * 400, status=413)


def test_new_version_replaces_old_content_and_index_refreshes(client):
    h = signup(client)
    kb = new_kb(client, h)
    first = upload(client, h, kb, "refund-policy.md", REFUND_MD)
    assert "5 working days" in ask(client, h, kb, "How many working days until my refund is paid?")["text"]

    same = upload(client, h, kb, "refund-policy.md", REFUND_MD, status=200)  # identical file: nothing changes
    assert same["version"] == 1

    v2 = upload(client, h, kb, "refund-policy.md", REFUND_MD.replace(b"5 working days", b"10 working days"), status=200)
    assert v2["id"] == first["id"] and v2["version"] == 2
    a = ask(client, h, kb, "How many working days until my refund is paid?")
    assert "10 working days" in a["text"] and "5 working days" not in a["text"]  # the cached index was rebuilt

    assert client.post(f"/api/documents/{first['id']}/reindex", headers=h).json()["chunk_count"] == 2


def test_deleted_document_is_no_longer_cited(client):
    h = signup(client)
    kb = new_kb(client, h)
    doc = upload(client, h, kb, "refund-policy.md", REFUND_MD)
    upload(client, h, kb, "shipping.txt", b"Orders ship within two days of payment.")
    assert client.delete(f"/api/documents/{doc['id']}", headers=h).status_code == 204
    a = ask(client, h, kb, "How many working days until my refund is paid?")
    assert all(s["document_id"] != doc["id"] for s in a["sources"])


def test_refuses_with_the_knowledge_base_message(client):
    h = signup(client)
    kb = new_kb(client, h)
    empty = ask(client, h, kb, "Anything at all?")
    assert empty["abstained"] and empty["sources"] == []  # no documents yet
    upload(client, h, kb, "refund-policy.md", REFUND_MD)
    a = ask(client, h, kb, "What is the hostel curfew?")
    assert a["abstained"] and a["mode"] == "abstain" and a["sources"] == []
    assert a["text"] == "Sorry, I could not find that. Email help@shop.example."


def test_llm_answers_may_only_cite_the_passages_they_were_given(client, monkeypatch):
    from assistant import answer as answer_mod
    from app import index

    monkeypatch.setattr(index, "settings", replace(index.settings, use_llm=True))
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    h = signup(client)
    kb = new_kb(client, h)
    upload(client, h, kb, "refund-policy.md", REFUND_MD)

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(reply):
        body = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
        return lambda req, timeout=None: Reply(body)

    monkeypatch.setattr(answer_mod.urllib.request, "urlopen", fake({"answer": "Refunds are paid within 5 working days.", "sources": [1]}))
    good = ask(client, h, kb, "How many working days until my refund is paid?")
    assert good["mode"] == "llm" and len(good["sources"]) == 1

    monkeypatch.setattr(answer_mod.urllib.request, "urlopen", fake({"answer": "Refunds take 2 hours.", "sources": [7]}))
    bad = ask(client, h, kb, "How many working days until my refund is paid?")
    assert bad["mode"] == "extractive" and "2 hours" not in bad["text"] and "rejected" in bad["note"]


def test_database_index_matches_the_evaluated_engine(client):
    """The eval numbers are measured on the file-based engine. Uploading the same articles into the product must give
    the same rankings, otherwise those numbers would not describe the product."""
    from sqlalchemy import select

    from app import db
    from app.index import cache
    from app.models import KnowledgeBase
    from assistant.core import Assistant
    from assistant.retriever import should_abstain

    h = signup(client)
    kb = new_kb(client, h, slug="placement-cell")
    for p in sorted(DOCS.glob("*.md")):
        upload(client, h, kb, p.name, p.read_bytes())
    engine = Assistant()
    with db.SessionLocal() as s:
        idx = cache.get(s, s.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb)))
    assert len(idx.chunk_ids) == len(engine.chunks)
    questions = [json.loads(line)["question"] for line in (DOCS.parent.parent / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert abs(idx.thresholds["min_bm25"] - engine.thresholds["min_bm25"]) < 1e-9  # scaling is a no-op on this corpus
    for q in questions:
        assert idx.retriever.docs_ranked(q, k=3) == engine.retriever.docs_ranked(q, k=3), q
        hits, _ = idx.search(q)
        assert should_abstain(hits, **idx.thresholds) == should_abstain(engine.retriever.search(q, k=5), **engine.thresholds), q


# ---------------------------------------------------------------- isolation and roles


def test_one_workspace_cannot_see_another(client):
    ha = signup(client, "a@a.example", "Team A")
    kb = new_kb(client, ha)
    doc = upload(client, ha, kb, "refund-policy.md", REFUND_MD)
    a = ask(client, ha, kb, "How many working days until my refund is paid?")

    hb = signup(client, "b@b.example", "Team B")
    assert client.get("/api/kbs", headers=hb).json() == []
    for method, url in [
        ("get", f"/api/kbs/{kb}"),
        ("get", f"/api/kbs/{kb}/documents"),
        ("get", f"/api/documents/{doc['id']}/chunks"),
        ("get", f"/api/conversations/{a['conversation_id']}"),
        ("get", f"/api/kbs/{kb}/analytics"),
        ("get", f"/api/kbs/{kb}/conversations"),
        ("delete", f"/api/documents/{doc['id']}"),
    ]:
        assert getattr(client, method)(url, headers=hb).status_code == 404, url  # 404, not 403: ids reveal nothing
    assert client.post(f"/api/kbs/{kb}/ask", json={"question": "refund days?"}, headers=hb).status_code == 404
    assert client.put(f"/api/messages/{a['message_id']}/feedback", json={"rating": -1}, headers=hb).status_code == 404
    # and B cannot continue A's conversation inside B's own knowledge base either
    kb_b = new_kb(client, hb, slug="team-b-help")
    assert client.post(f"/api/kbs/{kb_b}/ask", json={"question": "refund days?", "conversation_id": a["conversation_id"]}, headers=hb).status_code == 404


def test_agents_can_ask_but_not_change_content(client):
    h = signup(client)
    kb = new_kb(client, h)
    r = client.post("/api/users", json={"name": "Agent", "email": "agent@a.example", "password": PW, "role": "agent"}, headers=h)
    assert r.status_code == 201
    tok = client.post("/api/auth/login", json={"email": "agent@a.example", "password": PW}).json()["token"]
    ha = {"Authorization": f"Bearer {tok}"}
    assert client.post(f"/api/kbs/{kb}/ask", json={"question": "refund days?"}, headers=ha).status_code == 200
    assert client.post(f"/api/kbs/{kb}/documents", files={"file": ("x.md", REFUND_MD)}, headers=ha).status_code == 403
    assert client.post(f"/api/kbs/{kb}/keys", json={"name": "k"}, headers=ha).status_code == 403
    assert client.post("/api/kbs", json={"name": "New", "slug": "new-kb"}, headers=ha).status_code == 403
    assert client.post("/api/users", json={"name": "X", "email": "x@a.example", "password": PW}, headers=ha).status_code == 403
    assert client.get("/metrics", headers=ha).status_code == 403
    assert client.get("/metrics", headers=h).status_code == 200


# ---------------------------------------------------------------- feedback and analytics


def test_feedback_and_analytics(client):
    h = signup(client)
    kb = new_kb(client, h)
    upload(client, h, kb, "refund-policy.md", REFUND_MD)
    good = ask(client, h, kb, "How do I request a refund?")
    paid = ask(client, h, kb, "How many working days until my refund is paid?", conversation_id=good["conversation_id"])
    ask(client, h, kb, "What is the hostel curfew?")
    ask(client, h, kb, "When does the hostel gate close?")

    assert client.put(f"/api/messages/{good['message_id']}/feedback", json={"rating": 1}, headers=h).status_code == 204
    assert client.put(f"/api/messages/{paid['message_id']}/feedback", json={"rating": 1}, headers=h).status_code == 204
    # rating again replaces the earlier rating
    assert client.put(f"/api/messages/{paid['message_id']}/feedback", json={"rating": -1, "comment": "Too vague"}, headers=h).status_code == 204
    assert client.put(f"/api/messages/{paid['message_id']}/feedback", json={"rating": 0}, headers=h).status_code == 422

    an = client.get(f"/api/kbs/{kb}/analytics?days=7", headers=h).json()
    assert an["questions"] == 4 and an["refused"] == 2 and an["refusal_rate"] == 0.5
    assert an["feedback"] == {"up": 1, "down": 1}
    assert sum(d["questions"] for d in an["series"]) == 4 and len(an["series"]) == 8
    assert an["low_rated"][0]["question"] == "How many working days until my refund is paid?" and an["low_rated"][0]["comment"] == "Too vague"
    assert an["gaps"][0]["topic"] == "hostel" and an["gaps"][0]["count"] == 2

    convs = client.get(f"/api/kbs/{kb}/conversations", headers=h).json()
    assert len(convs) == 3
    first = next(c for c in convs if c["id"] == good["conversation_id"])
    assert first["messages"] == 4 and first["first_question"] == "How do I request a refund?" and first["rating_down"] == 1
    assert len(client.get(f"/api/kbs/{kb}/conversations?only_problems=true", headers=h).json()) == 3
    msgs = client.get(f"/api/conversations/{good['conversation_id']}", headers=h).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"] and msgs[3]["rating"] == -1
    assert msgs[1]["sources"][0]["text"]  # the cited passage is stored with the answer


# ---------------------------------------------------------------- public widget


def test_public_key_rate_limit_and_revocation(client):
    h = signup(client)
    kb = new_kb(client, h)
    upload(client, h, kb, "refund-policy.md", REFUND_MD)
    created = client.post(f"/api/kbs/{kb}/keys", json={"name": "Website", "rate_per_minute": 2}, headers=h).json()
    key = created["key"]
    assert key.startswith("hd_") and created["prefix"] == key[:10]
    assert "key" not in client.get(f"/api/kbs/{kb}/keys", headers=h).json()[0]  # shown once, stored only as a hash

    pk = {"X-API-Key": key}
    assert client.get("/api/public/kbs/shop-help", headers=pk).json()["name"] == "Shop help"
    first = client.post("/api/public/kbs/shop-help/ask", json={"question": "How do I request a refund?"}, headers=pk)
    assert first.status_code == 200 and first.json()["sources"]
    assert client.post("/api/public/kbs/shop-help/ask", json={"question": "Refund days?", "conversation_id": first.json()["conversation_id"]}, headers=pk).status_code == 200
    limited = client.post("/api/public/kbs/shop-help/ask", json={"question": "Third question"}, headers=pk)
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) >= 1

    fb = client.put(f"/api/public/kbs/shop-help/messages/{first.json()['message_id']}/feedback", json={"rating": 1}, headers=pk)
    assert fb.status_code == 204

    assert client.post("/api/public/kbs/shop-help/ask", json={"question": "refund?"}, headers={"X-API-Key": "hd_wrong"}).status_code == 401
    assert client.post("/api/public/kbs/shop-help/ask", json={"question": "refund?"}).status_code == 401
    other = new_kb(client, h, slug="other-help")
    other_key = client.post(f"/api/kbs/{other}/keys", json={"name": "Other"}, headers=h).json()["key"]
    assert client.post("/api/public/kbs/shop-help/ask", json={"question": "refund?"}, headers={"X-API-Key": other_key}).status_code == 401

    client.delete(f"/api/kbs/{kb}/keys/{created['id']}", headers=h)
    assert client.get("/api/public/kbs/shop-help", headers=pk).status_code == 401
    convs = client.get(f"/api/kbs/{kb}/conversations?channel=public", headers=h).json()
    assert len(convs) == 1 and convs[0]["messages"] == 4


def test_request_ids_and_health(client):
    r = client.get("/health", headers={"X-Request-ID": "req-7"})
    assert r.status_code == 200 and r.headers["X-Request-ID"] == "req-7"
    assert len(client.get("/health").headers["X-Request-ID"]) == 16
