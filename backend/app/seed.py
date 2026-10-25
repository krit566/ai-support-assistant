"""Demo data:  python -m app.seed

Creates a demo workspace with the placement-cell help centre (data/docs) as a knowledge base, two users and a
public key. Then it asks a list of sample questions through the real engine, spread over the last 14 days, so the
conversation list and analytics have something to show. Those conversations are flagged is_demo and labelled
"demo" in the UI; the thumbs up/down on them are invented for the demo, not real user feedback.

Passwords come from SEED_PASSWORD (default only for local use). Running it twice does nothing the second time.
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal
from .index import ask
from .ingest import parse
from .models import ApiKey, Conversation, Document, Feedback, KnowledgeBase, Message, User, Workspace
from .routes.kbs import _store_chunks
from .security import hash_password, new_api_key

DOCS = Path(__file__).resolve().parent.parent / "data" / "docs"
ADMIN_EMAIL = "admin@helpdesk.example"
AGENT_EMAIL = "agent@helpdesk.example"

SAMPLE_QUESTIONS = [
    # (question, demo rating or None, demo comment)
    ("Is there a fee to register for placements?", 1, ""),
    ("Can I withdraw after my interview is scheduled?", 1, ""),
    ("How long is the password reset link valid?", 1, ""),
    ("What happens if I miss a pre-placement talk?", None, ""),
    ("I got a job outside campus, what do I do?", 1, ""),
    ("What is a dream company?", None, ""),
    ("When do offer letters arrive?", -1, "Second sentence is about off-campus offers, not my question"),
    ("Who checks my documents for the background verification?", None, ""),
    ("How do I raise a complaint about a recruiter?", 1, ""),
    ("Can I update my CGPA after the semester results?", -1, "Mixed in something about offer letters"),
    ("What is the hostel curfew?", None, ""),
    ("When is the hostel mess closed on weekends?", None, ""),
    ("How do I apply for exam revaluation?", None, ""),
    ("What are the exam revaluation fees?", None, ""),
    ("Which buses go to the city campus?", None, ""),
    ("What is the library fine for late books?", None, ""),
]


def run() -> None:
    password = os.environ.get("SEED_PASSWORD", "demo-password-123")
    rnd = random.Random(7)  # fixed seed: the same demo data every time
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == ADMIN_EMAIL)):
            print("demo data already present")
            return
        ws = Workspace(name="Demo University")
        db.add(ws)
        db.flush()
        admin = User(workspace_id=ws.id, email=ADMIN_EMAIL, name="Demo Admin", password_hash=hash_password(password), role="admin")
        agent = User(workspace_id=ws.id, email=AGENT_EMAIL, name="Demo Agent", password_hash=hash_password(password), role="agent")
        db.add_all([admin, agent])
        kb = KnowledgeBase(
            workspace_id=ws.id,
            name="Placement Cell help centre",
            slug="placement-cell",
            description="Registration, applications, interviews, offers and documents (fictional demo articles).",
            team_name="a university Placement Cell",
            fallback_message="I could not find this in the Placement Cell help centre. Please write to placements@geu.example.edu.",
        )
        db.add(kb)
        db.flush()

        for path in sorted(DOCS.glob("*.md")):  # same files and order as the evaluated engine
            p = parse(path.name, path.read_bytes(), 5 * 1024 * 1024)
            doc = Document(kb_id=kb.id, filename=p.filename, doc_key=p.doc_key, title=p.title, kind=p.kind, size_bytes=p.size, sha256=p.sha256, text=p.text, uploaded_by=admin.id)
            db.add(doc)
            db.flush()
            _store_chunks(db, doc)

        key, digest = new_api_key()
        db.add(ApiKey(kb_id=kb.id, name="Website widget (demo)", prefix=key[:10], key_hash=digest, rate_per_minute=20))
        db.commit()

        now = datetime.now(timezone.utc)
        for i, (question, rating, comment) in enumerate(SAMPLE_QUESTIONS):
            # a random moment in the last 14 days, never in the future
            when = now - timedelta(days=13) + timedelta(minutes=rnd.randint(0, 13 * 24 * 60 - 60))
            conv = Conversation(kb_id=kb.id, user_id=agent.id if i % 3 else None, channel="console" if i % 3 else "public", is_demo=True, created_at=when)
            db.add(conv)
            db.flush()
            res = ask(db, kb, question)  # the real engine answers; nothing here is made up except the ratings
            a = res.answer
            db.add(Message(conversation_id=conv.id, kb_id=kb.id, role="user", text=question, created_at=when))
            msg = Message(
                conversation_id=conv.id, kb_id=kb.id, role="assistant", text=a.text, sources=res.passages, abstained=a.abstained,
                mode=a.mode, latency_ms=None, created_at=when + timedelta(seconds=1),
            )  # fmt: skip
            db.add(msg)
            db.flush()
            if rating is not None and not a.abstained:
                db.add(Feedback(message_id=msg.id, rating=rating, comment=comment, created_at=when + timedelta(seconds=30)))
        db.commit()
        print(f"demo workspace ready: {ADMIN_EMAIL} / {AGENT_EMAIL} (password from SEED_PASSWORD)")
        print(f"public widget: /chat/placement-cell?key={key}")


if __name__ == "__main__":
    run()
