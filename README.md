# Legal Contract RAG Analyzer

Backend-first system for uploading legal contracts (PDF/DOCX/TXT) and using
Retrieval-Augmented Generation to answer questions, detect and explain ~20
clause types with risk ratings, and summarize contract-level details
(parties, dates, obligations) — all grounded in cited excerpts from the
source document, not free-form LLM guessing.

Status: **Sprint 1 (scaffolding) complete.** No upload, extraction,
embeddings, retrieval, or LLM calls are wired up yet — see `CLAUDE.md` for
the full sprint plan and current status.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs for the interactive Swagger UI.

## Check the database

The SQLite database (`legal_rag.db`) and its tables (`documents`, `chunks`)
are created automatically on app startup (`init_db()` in
`app/db/init_db.py`, called from `app/main.py`'s startup event) — no manual
migration step is needed yet (no Alembic in this project).

To inspect it directly:

```bash
sqlite3 legal_rag.db ".tables"
sqlite3 legal_rag.db ".schema documents"
```

## Project layout

See `CLAUDE.md` for the architecture conventions, module layout, and hard
guardrails this project follows.
