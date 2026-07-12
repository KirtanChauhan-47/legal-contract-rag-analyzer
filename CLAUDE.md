# Legal Contract RAG Analyzer — Project Memory

## What this project is

A backend-only (FastAPI, Swagger-UI-tested — no frontend) system that
ingests legal contracts (PDF/DOCX/TXT), validates they ARE legal contracts,
chunks + embeds them, supports RAG-based Q&A with citations, and performs
clause-level + contract-level analysis across ~20 clause types. It is an
AI-assisted contract understanding/review tool, not a source of legal
advice.

Full sprint-by-sprint plan lives at:
`C:\Users\Kirtan\.claude\plans\i-want-to-build-cryptic-stonebraker.md`

## Tech stack (locked — do not re-litigate)

- FastAPI (service-layer architecture: routers are thin, services hold logic)
- SQLAlchemy ORM over SQLite (models written to be Postgres-portable — no
  SQLite-only types, use generic SQLAlchemy JSON/Text/etc.)
- ChromaDB (persistent, local) — single collection `contract_chunks`,
  metadata-filtered by `document_id` (NOT collection-per-document) — planned
  for Sprint 4, not yet installed/wired.
- PyMuPDF (fitz) for PDF, python-docx for DOCX, plain read for TXT —
  planned for Sprint 2.
- sentence-transformers `all-MiniLM-L6-v2` for embeddings (local, free,
  singleton-loaded) — planned for Sprint 4.
- Groq API for all generation/analysis LLM calls, accessed only through the
  `LLMProvider` interface — planned for Sprint 5+, currently stubbed.

## Architecture conventions

- `routers/` = HTTP layer only: parse request, call a service, return a
  schema. No business logic, no direct DB/model/LLM/vector-store access in
  routers.
- `services/` = all business logic, orchestration, LLM calls, vector store
  calls. Services access the DB through `app/db/repository.py`'s
  `Repository` helper (or a model-specific repository built on top of it),
  not raw `Session.query(...)` calls scattered around.
- `schemas/` = Pydantic request/response contracts, validated at the
  boundary.
- `models/` = SQLAlchemy ORM only, no business logic.
- `prompts/` = all LLM prompt templates live here, not inline in services,
  so they're easy to iterate on and review independently of orchestration
  code.
- LLM access always goes through `app/services/llm_service.py`'s
  `LLMProvider` interface (`get_llm_provider()` factory). No service may
  import a provider SDK (groq, google-generativeai, openai, ...) directly —
  this is what keeps the provider swappable.

## Document processing status machine

`uploaded -> extracted -> gated_rejected | chunked -> embedded -> analyzed | failed`

(`app/models/document.py`'s `DocumentStatus` enum.) Every endpoint should
check current status and fail clearly (409/422 via `ConflictError`/
`ValidationError` from `app/core/exceptions.py`) if called out of order.

## Hard guardrails — NEVER violate these

1. NEVER send a full document's raw/cleaned text to the LLM. All LLM calls
   (Q&A, clause detection, summary) must be built from retrieved CHUNKS only.
2. ALWAYS attach citations (chunk_id + quote + offsets) to any LLM-generated
   claim about document content. If a citation's quote can't be found
   verbatim (or near-verbatim) in the cited chunk, drop/flag it — don't
   trust LLM citations blindly.
3. ALWAYS run the contract gate before chunking/embedding/analyzing a
   document. Non-contract or unrecognizable uploads must be rejected with a
   clear reason, not silently processed.
4. Constrain LLM-output enums (clause_type, risk_level, contract_type)
   against fixed Python Enums defined in `app/core/*_taxonomy.py` (not yet
   created — lands in Sprint 6) — never trust free-text categorical output
   from the LLM without validation.
5. Never let extraction/LLM/parsing failures produce a raw 500 stack trace
   to the client — use the custom exception handlers
   (`app/core/error_handlers.py`) and set document `status`/`error_message`
   instead.
6. Chunks must always carry `char_start`/`char_end` offsets into
   `cleaned_text` — this is the backbone of every citation feature. Never
   break this invariant when touching chunking logic.
7. Re-running any analysis step (embed/analyze-clauses/summarize) on an
   already-processed document must replace prior results (upsert/delete-
   then-insert), never accumulate duplicates.
8. Chroma vectors and SQL rows must be deleted together — no orphaned
   vectors when a document is deleted or re-processed.
9. LLM access always goes through the `LLMProvider` interface — never a
   provider SDK imported directly into a service.
10. No Docker, Alembic, auth, Celery, LangGraph/agents/MCP, or frontend
    unless explicitly requested later — don't add infrastructure ahead of
    an actual need.

## Module layout

```
app/
├── main.py                 # FastAPI app factory, router mounting, startup event (init_db)
├── core/                    # config.py, exceptions.py, error_handlers.py, logging_config.py
│                             # (clause_taxonomy.py, auth.py land in later sprints)
├── db/                       # base.py (engine/Base), session.py (get_db), init_db.py, repository.py
├── models/                    # document.py, chunk.py  (analysis.py, chat.py land in later sprints)
├── schemas/                    # Pydantic schemas (empty until Sprint 2)
├── routers/                     # health.py  (documents.py, qa.py, clauses.py, summary.py land later)
├── services/                     # llm_service.py (interface + stub only for now)
├── prompts/                       # empty until Sprint 3+
└── utils/                          # empty until Sprint 2
```

## Coding conventions

- Sync SQLAlchemy sessions via the `get_db` FastAPI dependency (deliberate
  choice for MVP simplicity — not async).
- Config via `pydantic-settings` + `.env` (`app/core/config.py`), never
  hardcode API keys/paths.
- Structured logging via `app/core/logging_config.py`.
- All new LLM-calling services must depend on `LLMProvider` (constructor or
  parameter injection) so tests can supply a fake implementation — don't
  hit a real provider API in tests except 1-2 explicitly marked live tests
  (Sprint 8).
- No Alembic yet — schema changes go through `Base.metadata.create_all`
  (additive-only migrations by design per the sprint plan); if a
  destructive schema change is ever needed, flag it explicitly rather than
  quietly dropping/recreating `legal_rag.db`.

## Current sprint status

**Sprint 1 — COMPLETE.** Project skeleton, FastAPI app, config, SQLAlchemy
DB setup (`Document`, `Chunk` models), `GET /health`, generic repository
helper, stubbed `LLMProvider` interface, `requirements.txt`, `.env.example`,
README, this file. No upload/extraction/embeddings/retrieval/Groq
calls/clause detection yet — intentionally deferred.

**Next up — Sprint 2 (Document Ingestion Pipeline):** `POST
/documents/upload` (multipart validation, save to `data/uploads/`, extract
text via PyMuPDF/python-docx/plain-read), `GET /documents/{id}`, `GET
/documents`. Needs `app/schemas/document.py`, `app/routers/documents.py`,
`app/services/extraction_service.py`, `app/utils/file_validation.py`. Add
`python-multipart`, `pymupdf`, `python-docx` to `requirements.txt` when
starting this sprint.
