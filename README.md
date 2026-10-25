# HelpDesk AI

A support assistant that any team can set up on its own documents. Upload help articles, policies or FAQs (PDF,
Markdown, text); the assistant answers customers' questions **from those documents only**, shows **the exact passage
each answer came from**, and says **"I could not find this"** instead of guessing when the documents do not cover a
question. Teams see what customers ask, what was refused, and which answers were rated unhelpful.

React + TypeScript · FastAPI · PostgreSQL · SQLAlchemy + Alembic · hand-written BM25 + embeddings (RAG) · JWT + bcrypt ·
Docker · GitHub Actions

**[Full documentation (PDF)](docs/AI_Support_Assistant_Documentation.pdf)**

![Playground: a cited answer with its source passage, and a refused question](docs/screenshot-playground.png)

| Analytics | Documents | Public widget (phone, 375 px) |
|---|---|---|
| ![Analytics](docs/screenshot-analytics.png) | ![Documents](docs/screenshot-documents.png) | <img src="docs/screenshot-public-mobile.png" width="200" alt="Public chat on a phone"> |

## What it does

| For | Feature |
|---|---|
| Admins | Workspaces and team members (roles **admin** / **agent**); knowledge bases; drag-and-drop upload of PDF, Markdown and text; every document's passages visible; re-upload = new version; re-index; delete |
| Agents | Chat playground with numbered citations: click one to read the exact passage; thumbs up/down |
| Customers | Public chat page per knowledge base (`/chat/<name>?key=...`), no sign-in |
| Support leads | Conversations (filter: refused or thumbs-down), analytics: questions per day, refusal rate, helpful rate, answer time, **gaps** (refused questions grouped by topic, i.e. articles to write) and low-rated answers with comments |
| Developers | REST API with OpenAPI docs at `/docs`, publishable API keys with per-key rate limits, request IDs, `/metrics` |

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    UI[React console<br/>playground, documents,<br/>analytics, settings]
    W[Public chat page]
  end
  UI -- JWT --> API
  W -- X-API-Key<br/>rate-limited --> API
  subgraph API[FastAPI]
    R[Routes + roles<br/>workspace isolation] --> I[Ingest<br/>PDF / MD / TXT -> passages]
    R --> X[Index cache<br/>one per knowledge base]
    X --> E[Engine<br/>BM25 + embeddings, RRF,<br/>refuse rule, cited answer]
  end
  API <--> DB[(PostgreSQL<br/>documents, passages,<br/>conversations, feedback)]
```

```mermaid
flowchart TD
  Q[Question] --> R[Hybrid retrieval over the knowledge base's passages<br/>BM25 + embeddings, Reciprocal Rank Fusion]
  R --> T{Best passage weak<br/>on both signals?}
  T -- yes --> N["I could not find this…" (the knowledge base's own message)<br/>no model is called]
  T -- no --> G{LLM enabled?}
  G -- no --> E[Extractive answer: most informative sentences]
  G -- yes --> L[LLM answer from numbered passages]
  L --> V{Cites only passages<br/>it was given?}
  V -- no --> E
  V -- yes --> A[Answer + cited passages, stored with the conversation]
  E --> A
```

| Part | Where | What |
|---|---|---|
| Engine | `backend/assistant/` | Chunking, tokenising, BM25 (written out by hand), LSA / sentence-transformers / API embeddings, Reciprocal Rank Fusion, the refuse rule, extractive and LLM answers. Unchanged in behaviour from the evaluated version |
| Product API | `backend/app/` | `models.py` (9 tables), `security.py` (bcrypt, JWT, API keys), `ingest.py` (upload checks and parsing), `index.py` (per-knowledge-base index cache), `analytics.py`, `routes/` |
| Migrations | `backend/migrations/` | Alembic; the tests build their schema by running them |
| Frontend | `frontend/src/` | React Router pages, a shared chat component, hand-written SVG charts |

### How the index is stored, and why not pgvector

Passages (and, for embedders that do not depend on the corpus, their vectors) are stored in PostgreSQL. Each server
process keeps an in-memory search index per knowledge base, rebuilt when the knowledge base changes: every upload,
re-index or delete increments `knowledge_bases.index_version` **in the same transaction**, and before answering the
cached index's version is compared with the database's. That keeps several server processes correct without a message
bus.

BM25 needs word statistics over the whole knowledge base and LSA is fitted on the whole knowledge base, so both are
rebuilt from all passages anyway; for a few thousand passages that takes well under a second. **pgvector** would let
the database do nearest-neighbour search for very large collections, but keyword search would then need a separate
full-text index and the two rankings would still be fused in the application. It becomes worth it at roughly 100k+
passages or when memory per process matters.

### A finding while building it: thresholds do not transfer between corpus sizes

The "refuse" thresholds were tuned on the 53-passage placement-cell corpus. In the first version a 2-passage knowledge
base refused **everything**: BM25 scores shrink with corpus size (a word found in 1 of 2 passages weighs 0.69, in 1
of 53 it weighs 3.58), so the tuned BM25 bar of 3.5 was unreachable. The BM25 threshold is now kept in units of "one
rare word" and converted for each knowledge base's size. On the placement corpus the conversion is exactly a no-op, and
a test checks that the product index makes the **same rankings and the same refuse decisions** as the evaluated engine
for all 46 evaluation questions, so the numbers below describe the product.

## Evaluation (unchanged by the product work)

46 questions written for this project: 37 answerable (each labelled with the article that answers it and one key fact)
and 9 that the help centre does not cover. Split into **dev (14)** for choosing thresholds and **test (32)** for
reporting. Offline LSA embedder, extractive answers (`backend/eval/results_lsa.json`):

| Metric (test split) | Value |
|---|---|
| Right article ranked first (recall@1), hybrid | 89% (24/27) |
| Right article in top 3 (recall@3) | 96% (26/27) |
| MRR | 0.92 |
| Answer correct: cites the right article **and** contains the key fact | 70% (19/27) |
| Unanswerable questions correctly refused | 3/5 |
| Answerable questions wrongly refused | 1/27 |

- **Retrieval is strong, sentence choice is weak:** most wrong answers found the right article but quoted the wrong
  sentence. The LLM answer step is implemented but not evaluated, so no number is claimed for it.
- **Refusing is the weak spot.** Example from the demo: "Which buses go to the city campus?" is answered with the
  off-campus offers article because "campus" matches; "How do I raise a complaint about a recruiter?" is refused
  although a grievances article exists. Both kinds of error are visible in the Analytics and Conversations pages.
- **Caveats:** the articles and questions were written by the same person and the test set is small (one question is
  about 3 points), so these scores are optimistic. CI fails the build if hybrid recall@3 drops below 0.90.

## Security and privacy

| Concern | How |
|---|---|
| Passwords | bcrypt; same error and similar timing for an unknown email and a wrong password |
| Sessions | JWT (HS256, algorithm pinned, expiry); the role is re-read from the database on every request |
| Isolation | Every query is scoped to the caller's workspace; another team's ids return **404**, not 403 |
| Roles | Agents can ask, rate and read analytics; only admins change documents, keys, users and settings |
| Public keys | Random, shown once, stored as SHA-256; work only for asking one knowledge base; revocable; per-key rate limit (429 + `Retry-After`) |
| Uploads | Size limit (413), extension allow-list and content check (415: a renamed binary is rejected), client file names sanitised |
| LLM | Optional; the key lives only on the server; answers must cite passages they were given |
| Logs | One JSON line per request and per answer with request ID, outcome, sources and timing, **never the question text** |

## Run it

**Docker (everything):**

```bash
cp .env.example .env        # set JWT_SECRET and POSTGRES_PASSWORD
docker compose up --build   # http://localhost:8080
docker compose exec backend python -m app.seed   # demo workspace (prints the public widget link)
```

**Development:**

```powershell
cd backend
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
$env:DATABASE_URL = "postgresql://user:pass@localhost:5432/helpdesk"
alembic upgrade head
python -m app.seed                       # demo users: admin@helpdesk.example / agent@helpdesk.example
uvicorn app.main:app --port 8103         # API docs: http://127.0.0.1:8103/docs
python -m pytest -q                      # 42 tests on a real PostgreSQL (embedded if DATABASE_URL is unset)
python eval/run_eval.py                  # evaluation

cd ../frontend
npm install
npm run dev                              # http://localhost:5183 (proxies /api to :8103)
npm test                                 # 11 tests, including axe accessibility checks
```

The demo seed sets passwords from `SEED_PASSWORD` (a local-only default otherwise). Its sample conversations are
answered by the real engine but their thumbs up/down are invented; they are marked **demo** in the UI.

**Deploy:** `render.yaml` is a Render blueprint (PostgreSQL + API + static site); see the comments in it for the two
URLs to set after the first deploy.

## Tests

| Suite | Covers |
|---|---|
| `backend/tests/test_assistant.py` (15) | The engine: chunking, BM25, retrieval on known questions, refusals, LLM citation check, the original single-corpus API |
| `backend/tests/test_product.py` (21) | Sign-up/login, PDF/MD/TXT uploads and 8 kinds of bad upload, versions and cache refresh, deleted documents no longer cited, per-knowledge-base refusal message, LLM citations, **product index = evaluated engine**, workspace isolation, roles, feedback, analytics, API keys, rate limit, revocation |
| `backend/tests/test_units.py` (6) | Threshold scaling, sliding-window rate limit (fake clock), file-name sanitising, text chunking |
| `frontend/src/test` (11) | Sign-in, redirect when signed out, citation panel, follow-up questions, refusals, shareable `?q=` links, upload checks, analytics, public widget never sends a session token, axe scans |

## Limitations and next steps

- Refusal and sentence choice are the weak parts (see Evaluation). Next: evaluate pretrained embeddings and the LLM mode
  on the same test split; per-knowledge-base threshold tuning from the thumbs-down data.
- The rate limiter and index cache live in process memory: correct for one process (the limiter allows the full limit
  per process). With several instances, move the limiter to Redis.
- Uploads are parsed inside the request; very large PDFs would need a background job queue.
- The session token is kept in `localStorage` (simple, but readable by injected scripts); an httpOnly cookie with CSRF
  protection is the stronger choice for production.
- Scanned PDFs without a text layer are rejected (no OCR).

## Things to be ready to explain

- What BM25's `k1` and `b` do; why rank fusion (RRF) instead of adding BM25 and cosine scores.
- Why the thresholds are chosen on dev and reported on test, and why the BM25 threshold had to be rescaled per corpus.
- How the index cache stays correct with several server processes (`index_version` bumped in the same transaction).
- Why another workspace's ids return 404; why API keys are stored hashed but passwords with bcrypt.
- Why an LLM's citations are checked against the passages it was actually given.
- Why the public key is not a secret, and what still protects the knowledge base.
