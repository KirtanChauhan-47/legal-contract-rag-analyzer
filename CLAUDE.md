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
├── schemas/                    # document.py, chunk.py  (qa.py, clause.py, summary.py land later)
├── routers/                     # health.py, documents.py  (qa.py, clauses.py, summary.py land later)
├── services/                     # llm_service.py (interface + stub only), extraction_service.py,
│                                   # document_service.py (upload + process orchestration),
│                                   # contract_gate_service.py, cleaning_service.py, chunking_service.py
├── prompts/                       # contract_gate_prompt.py
└── utils/                          # file_validation.py
```

`app/db/chunk_repository.py` holds Chunk-specific queries (list-by-document,
replace-for-document), kept out of the generic `Repository` per its own
docstring — model-specific query logic gets its own module.

Note: `document_service.py` isn't named in the original sprint plan but follows
directly from the stated layering rule (routers thin, services orchestrate) —
it owns save-to-disk + extraction + DB persistence so `routers/documents.py`
stays a pure parse-call-return layer.

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

## Local verification conventions

- `resources/` holds persistent sample documents (NDA, non-contract, etc.)
  for manual/live testing — committed to git, never deleted or regenerated
  between sessions. Add more sample contracts there directly rather than
  having them recreated ad hoc each session.
- `.env` (with real API keys) is never deleted between test runs — it's
  gitignored, so it was never going to be committed anyway; leave it in
  place so keys don't need re-entering every session.
- `legal_rag.db` and `data/` (uploads + Chroma) are treated as persistent
  local dev state by default — not wiped before every verification pass,
  so upload/process/embed doesn't need repeating just to test something
  downstream. Only reset them deliberately (and say so explicitly) when a
  genuinely clean slate is needed, e.g. testing the empty-state path or
  after a destructive schema change.
- Throwaway one-off scripts written purely to check something (e.g. a
  quick offset-verification script) are still fine to delete after use —
  the persistence rule above is about fixtures and dev state, not scratch
  tooling.

## Current sprint status

**Sprint 1 — COMPLETE.** Project skeleton, FastAPI app, config, SQLAlchemy
DB setup (`Document`, `Chunk` models), `GET /health`, generic repository
helper, stubbed `LLMProvider` interface, `requirements.txt`, `.env.example`,
README, this file.

**Sprint 2 — COMPLETE.** `POST /documents/upload` (multipart upload,
extension/size/empty-file validation, saved to `data/uploads/{uuid}_{name}`,
text extracted via PyMuPDF/python-docx/plain-read), `GET /documents/{id}`
(with `?include_text=true` to fetch full raw text), `GET /documents`
(paginated list). Extraction failures set `status=failed` +
`error_message` instead of raising — verified live with a corrupt/rejected
upload. Verified live end-to-end with real `.txt`/`.docx`/`.pdf` sample
files: all three extracted correctly, files persisted to disk, DB rows
correct, 404 handling correct. Still no gate/cleaning/chunking (Sprint 3),
embeddings (Sprint 4), or LLM calls (Sprint 5+).

**Sprint 3 — COMPLETE.** `POST /documents/{id}/process` runs the gate →
clean → chunk pipeline; `GET /documents/{id}/chunks` inspects results.
Contract gate is a two-tier heuristic (keyword/pattern scoring) +
LLM-confirmation-for-ambiguous-cases design; since `LLMProvider` is still
stubbed (Sprint 1), ambiguous cases currently fall back to a heuristic-only
decision via a caught `NotImplementedError` — this will start using real
Groq confirmation automatically once Sprint 5 wires it up, no code change
needed here. Cleaning is deterministic (whitespace/hyphenation/quote
normalization). Chunking detects heading lines (numbered sections,
Section/Article, ALL-CAPS) to find section boundaries, sub-splits oversized
sections into overlapping word windows, and falls back to paragraph
splitting when no structure is found. Re-processing a document replaces
its chunks rather than accumulating duplicates (`ChunkRepository.
replace_for_document`).

Verified live: a realistic multi-clause NDA was accepted and chunked into
10 chunks with correct short section labels (e.g. `"1. Confidentiality."`,
not the whole clause body — this was caught and fixed during verification,
since headings and body text often share one line in real contracts); a
non-contract text (gardening article) was correctly gated-rejected with a
clear reason; every chunk's `char_start`/`char_end` was verified to slice
`cleaned_text` back to exactly the stored chunk text.

**Sprint 4 — COMPLETE.** `POST /documents/{id}/embed` embeds all of a
document's chunks with a singleton `all-MiniLM-L6-v2` model
(`app/services/embedding_service.py`) and upserts them into a single
persistent ChromaDB collection `contract_chunks`
(`app/services/vector_store_service.py`), metadata-filtered by
`document_id` (not collection-per-document, per the locked design).
`embedding_id` (`doc{document_id}_chunk{chunk_id}`) is recorded back onto
each `Chunk` row. `GET /documents/{id}/search?q=...` is a raw semantic
search debug endpoint (no LLM). Re-processing or re-embedding a document
purges its old vectors first (`vector_store_service.
delete_vectors_for_document`) so nothing orphans or duplicates — this is
called both when `/process` replaces chunks and at the start of `/embed`.
Status machine now enforced: `/embed` requires `chunked`/`embedded`
status, `/search` requires `embedded` status, both via `ConflictError`
(409).

Verified live: uploaded and processed a real NDA, confirmed `/search`
returned a 409 before embedding, embedded it, then ran three natural-
language queries ("how can this agreement be terminated", "what happens
if there are damages", "which state law applies") — each correctly
matched its corresponding clause (Term and Termination, Limitation of
Liability, Governing Law respectively) with a clear distance gap over
irrelevant chunks, proving real semantic (not keyword) search. Also
verified re-embedding is idempotent: chunk count and Chroma vector count
both stayed at 10 after embedding twice — no duplicates.

**Sprint 5 — COMPLETE.** `POST /documents/{id}/ask` retrieves top-k chunks
(`app/services/retrieval_service.py`, shared with `/search`), builds a
grounded prompt (`app/prompts/qa_prompt.py`) instructing the LLM to answer
only from the excerpts and cite verbatim quotes, calls the real
`GroqLLMProvider` (`llm_service.py`, JSON mode via
`response_format={"type": "json_object"}`), parses the structured
`{answer, citations}` response, and drops any citation whose quote can't
be found verbatim in its cited chunk before persisting. `GET
/documents/{id}/chat` returns full history. Chat is modeled as
`ChatSession`/`ChatMessage` (`app/models/chat.py`,
`app/db/chat_repository.py`), with `session_id` as an external UUID (same
pattern as `Document.uuid`) — omit it on `/ask` to start a new session, or
pass a prior one to continue a conversation. If the closest retrieved
chunk's distance exceeds `MAX_DISTANCE_FOR_ANSWER` (1.5, tuned empirically
against MiniLM output), the endpoint returns "not relevant" without
calling the LLM at all — cost savings and a hallucination guard in one.
`LLMProvider` factory (`get_llm_provider()`) now supports `groq` in
addition to `stub`; the contract gate's ambiguous-case LLM confirmation
(Sprint 3) automatically starts using real Groq calls too now that
`LLM_PROVIDER=groq` is set, with no code changes needed there.

Verified live end-to-end with a real Groq API key: asked "How can this
agreement be terminated?" — got a correct, grounded answer citing chunk 3
(Term and Termination) with a verbatim-verified quote; asked a follow-up
in the same session ("What law governs this agreement?") — correctly
retrieved chunk 4 (Governing Law); asked an out-of-scope question ("tax
withholding rate for employee bonuses") — correctly short-circuited to
the "not relevant" response without an LLM call; verified an invalid
`session_id` returns a clean 409, not a crash. Also confirmed (with a
still-stub-provider test before the key was wired up) that a missing LLM
integration fails cleanly through the generic exception handler — no raw
stack trace ever reaches the client, matching guardrail #5.

## Mid-testing fix: retrieval quality (between Sprint 5 and Sprint 6)

**Bug found:** manual testing with a real licensing agreement
(`resources/agreement_doc1.pdf`) showed pure vector search under-ranking
or entirely missing chunks containing exact legal defined terms. Searching
`Allowable Deductions` (a phrase that appears verbatim in the Payment/
Royalty chunk) either returned nothing at low `top_k`, or ranked the
correct chunk as low as #9 with unrelated chunks (Basic Provisions,
Indemnification, warranty boilerplate) ranked above it. Root cause: Chroma
was only returning its own top-N nearest-by-embedding-distance chunks, and
if a chunk with a matching literal phrase didn't happen to also be
semantically close by embedding distance, it was never in the candidate
pool at all. Separately, `chunking_service.py`'s ALL-CAPS heading regex
was too permissive — it matched any long ALL-CAPS line, so wrapped
continuation lines from warranty/liability disclaimer paragraphs (e.g.
`"THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE OR ANY LEVEL OF"`) were misread as section headings, polluting
`section_label` values.

**Fix implemented:**
- `retrieval_service.retrieve()` is now hybrid: it still pulls a wider
  Chroma candidate pool (top 20, up from top-k), but also scores **every**
  chunk in the document (via `ChunkRepository.list_by_document`, the SQL
  source of truth) for exact-phrase containment and keyword-token overlap
  against the raw query. A chunk with a verbatim phrase match is included
  and ranked even if Chroma's embedding distance alone wouldn't have
  surfaced it. Score = `(5.0 if exact_phrase_match) + keyword_score +
  vector_similarity` (vector L2 distance converted to a bounded 0..1
  similarity). Response payload now includes `vector_distance`,
  `keyword_score`, `exact_phrase_match`, `combined_score`, and
  `match_reason` so ranking decisions are inspectable, not just a bare
  distance number.
- Both `GET /documents/{id}/search` and `POST /documents/{id}/ask` go
  through this same hybrid `retrieve()` — no separate code path for
  debug search vs. RAG Q&A. `qa_service`'s "is this actually relevant"
  gate (previously a raw vector-distance threshold) now checks
  `exact_phrase_match OR keyword_score >= 0.5 OR vector_distance <=
  threshold` — any one signal is enough, matching the new ranking logic.
- `chunking_service.HEADING_PATTERN`'s ALL-CAPS alternative now caps
  matches at 6 space-separated words with no commas (real headings are
  short: `"INDEMNIFICATION"`, `"GOVERNING LAW AND FORUM"`; wrapped
  disclaimer continuation lines are long and comma-heavy) — this alone,
  combined with the `$`-anchored full-line match, rejects continuation
  lines without needing a separate validation pass.

**Regression queries used** (all now rank the correct chunk #1 or #2,
verified live against `resources/agreement_doc1.pdf`): `Allowable
Deductions`, `what is allowable deduction`, `what deductions are allowed
from net revenue`, `Annual Minimum Guarantee`, `Royalty Statement`,
`Governing Law`, `Termination`, `Indemnification`, `Limitation of
Liability`. Also verified `/ask` for "What are Allowable Deductions?" and
"What deductions are allowed from Net Revenue?" — both produced correct,
grounded answers citing the Payment/Royalty chunk with a verbatim-verified
quote.

**Expected behavior going forward:** any future retrieval work should
keep going through `retrieval_service.retrieve()` rather than calling
`vector_store_service.query()` directly — that's what keeps `/search` and
`/ask` (and Sprint 6's clause detection) behaving consistently. Chunking
heading detection is heuristic, not perfect — if a future document
surfaces another aggressive-heading false positive, tighten
`HEADING_PATTERN` further rather than adding a second ad hoc filter pass.

**Known remaining limitation (unrelated to this fix, not addressed):**
`agreement_doc1.pdf` extraction has a font-encoding artifact where
semicolons render as `Í¾` in `raw_text`/`cleaned_text` (a PyMuPDF/PDF font
quirk, not a retrieval or chunking bug) — citations still verify correctly
since the artifact is consistent between stored and quoted text, but it's
a text-quality issue worth revisiting if it shows up in more documents.

## Sprint 5.1 hardening pass (between the retrieval fix and Sprint 6)

A focused bugfix/hardening pass, not a new sprint of features:

1. **Chat-session document scoping bug fixed.** `ChatSessionRepository`
   previously exposed `get_by_uuid(session_uuid)`, which looked up a
   session by UUID with no document filter — a session UUID created for
   document A could be reused via document B's `/ask` and would silently
   succeed. Replaced with `get_by_uuid_for_document(session_uuid,
   document_id)`, which requires both to match; `qa_service.ask()` now
   raises a 409 `ConflictError` if the session doesn't belong to the
   requested document. Verified both by a unit test and live via the API
   (a real session from one embedded document was rejected against a
   second embedded document).
2. **Automated pytest suite added** (`tests/`, run via `python -m pytest
   tests/ -v`) — 11 tests covering: exact-phrase retrieval ranking (the
   Sprint 5 fix), cross-document session rejection, invalid citation
   quotes being dropped, an LLM answer being withheld when all its
   citations fail verification, unparseable/malformed LLM JSON being
   withheld rather than passed through, Markdown-fenced JSON being
   parsed, and chunk-replacement idempotency (both single- and
   multi-document). Tests use an in-memory SQLite DB and monkeypatch the
   embedding model / Chroma / LLM provider — no network access or Groq
   key needed to run them.
3. **Groq JSON parsing hardened** (`qa_service._parse_llm_json`): strips
   a `\`\`\`json ... \`\`\`` Markdown fence if present before parsing,
   validates the parsed shape (`dict` with `answer: str` and `citations:
   list`) before trusting it, and returns `None` — never a
   partially-trusted value — on any failure.
4. **Ungrounded answers are now withheld, not passed through.** Previously,
   if the LLM's citations all failed verification, the citations list came
   back empty but the model's raw answer text was still returned as if it
   were reliable. Now, whenever `verified_citations` is empty after
   parsing (whether due to failed verification, unparseable JSON, or
   invalid shape), `qa_service.UNGROUNDED_ANSWER` is returned instead of
   the model's text — an unsupported claim about a legal document is
   never handed back as if it were grounded, no matter how confident it
   sounds.
5. **README.md rewritten** — previously still said "Sprint 1 complete";
   now documents the real pipeline, all endpoints, setup (including the
   Groq key), the hybrid retrieval design, citation/grounding safety
   behavior, a sample curl workflow, how to run tests, and current
   limitations.

No API response shapes changed as a result of this pass (the `/ask`
response shape is unchanged; only its content differs when citations fail)
and no architecture was rewritten — this was inspection + targeted fixes
against the existing implementation.

**Next up — Sprint 6 (Clause Detection & Structured Analysis):** `POST
/documents/{id}/analyze-clauses` scans the ~20-clause taxonomy, doing a
targeted retrieval + LLM call per clause type (skipping types with no
close-enough match), returning `{clause_type, found,
plain_language_explanation, risk_level, why_it_matters, citation,
recommendation}` per type — reusing the retrieve → prompt → LLM →
verify-citation pattern established in Sprint 5. Needs `app/core/
clause_taxonomy.py` (fixed Enum of clause types + risk levels),
`app/services/clause_service.py`, `app/prompts/
clause_detection_prompt.py`, `app/models/analysis.py` (`ClauseAnalysis`),
`app/schemas/clause.py`, plus `GET /documents/{id}/clauses`. Re-running
must replace prior results per document_id+clause_type (same
idempotency pattern as chunk/vector replacement).
