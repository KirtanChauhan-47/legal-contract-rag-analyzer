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
├── core/                    # config.py, exceptions.py, error_handlers.py, logging_config.py,
│                             # clause_taxonomy.py  (auth.py lands later, if ever requested)
├── db/                       # base.py (engine/Base), session.py (get_db), init_db.py, repository.py,
│                               # chunk_repository.py, chat_repository.py, analysis_repository.py
├── models/                    # document.py, chunk.py, chat.py, analysis.py (ClauseAnalysis)
├── schemas/                    # document.py, chunk.py, qa.py, clause.py  (summary.py lands Sprint 7)
├── routers/                     # health.py, documents.py (upload/process/embed/search/clauses),
│                                  # qa.py (ask/chat)
├── services/                      # llm_service.py (LLMProvider interface + StubLLMProvider +
│                                    # GroqLLMProvider), extraction_service.py, document_service.py
│                                    # (upload/process/embed/search orchestration),
│                                    # contract_gate_service.py, cleaning_service.py,
│                                    # chunking_service.py, embedding_service.py,
│                                    # vector_store_service.py, retrieval_service.py (hybrid
│                                    # retrieve() + is_relevant(), shared by search/ask/clauses),
│                                    # citation_verification.py (shared JSON-parsing + citation
│                                    # verification, used by qa_service and clause_service),
│                                    # qa_service.py, clause_service.py
├── prompts/                        # contract_gate_prompt.py, qa_prompt.py, clause_detection_prompt.py
└── utils/                           # file_validation.py
```

`app/db/chunk_repository.py`, `chat_repository.py`, and `analysis_repository.py`
each hold model-specific queries (list-by-document, replace-for-document),
kept out of the generic `Repository` per its own docstring.

Note: `document_service.py` isn't named in the original sprint plan but follows
directly from the stated layering rule (routers thin, services orchestrate) —
it owns save-to-disk + extraction + DB persistence so `routers/documents.py`
stays a pure parse-call-return layer. Likewise `qa_service.py` and
`clause_service.py` are called directly from their routers rather than via
`document_service`, since routing every call through a pass-through layer
would add indirection without value.

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

**Sprint 6 — COMPLETE.** `POST /documents/{id}/analyze-clauses` scans the
fixed 20-clause taxonomy (`app/core/clause_taxonomy.py` — `ClauseType`,
`RiskLevel`, `CLAUSE_INFO` labels/descriptions, `CLAUSE_SEARCH_QUERIES`
aliases) and `GET /documents/{id}/clauses` lists persisted results.
`ClauseAnalysis` (`app/models/analysis.py`) has a `UniqueConstraint` on
`(document_id, clause_type)` as defense-in-depth alongside
`ClauseAnalysisRepository.replace_for_document`'s delete-then-insert
strategy (`app/db/analysis_repository.py`) — the same idempotency pattern
as chunks/vectors.

Retrieval-first, not 20 unconditional LLM calls: `clause_service.
_analyze_one_clause()` queries every alias for a clause type through the
existing `retrieval_service.retrieve()` (reused unchanged), merges
candidates by `chunk_id` keeping each one's best `combined_score` across
aliases, and only calls the LLM if the best merged candidate clears
`retrieval_service.is_relevant()` — otherwise the clause is stored
`present=false` with no LLM call at all. `is_relevant()` and its
thresholds (`MAX_DISTANCE_FOR_RELEVANCE`, `MIN_KEYWORD_SCORE_FOR_RELEVANCE`)
were extracted out of `qa_service` into `retrieval_service` specifically
so both consumers share one bar for "is this evidence good enough to act
on" — `qa_service` was refactored to call the shared version, no behavior
change there. Likewise, JSON-parsing and citation-verification logic
(Markdown-fence tolerance, shape validation, verbatim quote checking) was
extracted from `qa_service` into a new `app/services/
citation_verification.py`, used by both `qa_service` and `clause_service`.

Grounding: if the model claims `present=true` but none of its citations
verify against the retrieved chunk text, the result is stored as absent,
not as an unsupported "present" finding. `risk_level` is validated against
`RiskLevel`'s fixed values (falling back to `"unknown"` for anything else)
and the prompt (`app/prompts/clause_detection_prompt.py`) explicitly frames
`risk_level`/`risk_explanation` as a heuristic review signal, not legal
advice — this framing is also repeated in the README disclaimer.

Verified live against `agreement_doc1.pdf` (see `resources/`): 16 of 20
clause types correctly detected present with grounded citations (e.g.
`payment` cited the same Allowable Deductions chunks found in the
retrieval-quality fix; `confidentiality` correctly cited a cross-reference
to a separate NDA rather than fabricating clause text); `force_majeure`,
`non_compete`, `non_solicitation`, and `obligations` correctly came back
absent. Re-running against the same document kept exactly 20 rows (20
distinct `clause_type` values, no duplicates) both before and after a
second run.

**Known limitations observed:**
- In this live run, all 20 clause types happened to clear the
  `is_relevant()` gate and triggered an LLM call (confirmed via Groq
  request logs: 20 successful completions) — the 4 "absent" results came
  from the LLM's own judgment, not the retrieval-gate skip. The skip path
  itself *is* correctly exercised and passing in the automated test suite
  (`test_absent_clause_skips_llm_call`, `test_no_candidates_at_all_skips_
  llm_call`), using deliberately irrelevant chunks — but this particular
  document's broad shared vocabulary meant no clause-type alias came back
  with literally zero evidence. Short 1–2-token aliases (e.g.
  `"non-compete"` → tokens `["non", "compete"]`) are especially prone to
  this: a single common-word partial match (e.g. any chunk containing
  "non-exclusive") can cross the 0.5 keyword-score threshold on its own.
  Not incorrect (the LLM still correctly says "not present"), but weaker
  as a cost-saving gate for short aliases than for longer, more specific
  ones. Worth revisiting (e.g. weighting rarer tokens higher, similar to
  TF-IDF) if LLM-call volume becomes a real cost concern.
- Sprint 5.1 added an automated test for chunk-replacement idempotency,
  but not yet for Chroma vector-upsert idempotency — recorded as a known
  gap, not blocking, per explicit instruction when this sprint was
  assigned.
- The Groq free tier has a daily token quota (100k Tokens Per Day on the
  tier used during development); heavy same-day testing (multiple full
  20-clause analysis runs plus `/ask` calls) can hit `429
  rate_limit_exceeded`. The Groq SDK auto-retries transient 429s
  internally, but a hard daily-quota 429 now propagates as a clean 429
  `rate_limited` response (see Sprint 6.1 below) rather than a generic 500.
  Not a code bug — an external operational constraint worth knowing about
  when testing multiple sprints' worth of LLM calls in one day.

## Sprint 6.1 — clause-analysis cost measurement + optimization

A measurement-first reliability/efficiency pass, prompted by hitting the
Groq daily quota mid-Sprint-6-testing (`429 rate_limit_exceeded`, one
clause call alone requesting ~2,883 tokens).

**Measured (real, against `resources/agreement_doc1.pdf`, document_id 2):**
20/20 clause types reached the LLM every run (~50,000–52,000 total tokens
per full analysis — cross-checked against 3 real Groq calls with
`response.usage`, not just an approximation). Root-caused *why* all 20
passed the relevance gate: (a) short 2-token aliases like `"non-compete"`
can hit the 0.5 keyword-overlap threshold via one common-word partial
match (confirmed: `non_compete`/`non_solicitation` passed on kw=0.50 alone
and were correctly absent — 2 plausibly-avoidable calls); (b) ubiquitous
contract vocabulary saturates keyword scoring even at kw=1.00
(`obligations` — needs rarer-token/TF-IDF weighting, not a bigger
threshold, to fix); (c) **exact-phrase matching is not a safe shortcut
either** — `force_majeure` hit `exact_phrase_match=True` (the term is
mentioned as a termination trigger) yet the clause is genuinely absent, so
an "exact phrase ⇒ skip the LLM and assume present" heuristic would have
been wrong; (d) `dispute_resolution` sits on a near-identical signal
profile to the two avoidable calls (kw=0.50, moderate vector distance) but
is a **true positive** — proof that a single document's data is not
enough to safely calibrate a new hard relevance threshold without risking
recall loss. Full table and reasoning kept in conversation history; the
conclusion — do not tighten the shared relevance gate on one document's
evidence — is what's binding here.

**Implemented (this pass):**
1. **Groq rate limits mapped to a clean 429.** `GroqLLMProvider.generate()`
   catches `groq.RateLimitError` and raises a new `RateLimitedError` (`app/
   core/exceptions.py`, status 429, error_code `rate_limited`), preserving
   a real `Retry-After` header when Groq's response includes one via
   `error_handlers.py`'s `AppException` handler — never the raw provider
   message text, which can contain org/account identifiers.
2. **`MAX_CHUNKS_FOR_PROMPT` lowered from 6 to 3**, plus near-duplicate
   suppression (`clause_service._select_prompt_chunks`/`_is_near_duplicate`,
   token-Jaccard overlap ≥0.85 against already-selected chunks) — found and
   fixed a real case of waste: `governing_law` was citing the same
   sentence from two chunks (60 and 61) that contain near-identical text.
   Verified safe by comparing, per clause type, the chunk_ids actually
   cited in the prior full (MAX=6) run against what the new selection
   would include: 15/16 previously-cited clause types keep 100% of their
   citation evidence unchanged; the one exception (`jurisdiction`) lost
   access to chunk 60 specifically *because* it's the near-duplicate of
   chunk 61 (which is retained) — i.e. the loss is the dedup mechanism
   working as intended, not a grounding regression.
3. **Analysis result caching.** `POST /documents/{id}/analyze-clauses?
   force=false` (default) now skips calling the LLM entirely if a
   `ClauseAnalysisRun` row (new table, `app/models/analysis.py`) shows the
   current fingerprint already matches the last successful run.
   `clause_service._compute_analysis_fingerprint()` hashes chunk text
   (captures document + re-chunking changes), the clause taxonomy/alias
   dict, the full `SYSTEM_PROMPT` text, and the configured Groq/embedding
   model names — deliberately hashing actual content rather than
   maintaining manually-bumped version constants, so nothing can be
   forgotten. `force=true` bypasses the cache unconditionally.

**Verified:** all 25 automated tests pass (7 new: rate-limit mid-run
leaves prior rows untouched, cache-hit skips the LLM, `force=true`
bypasses the cache, changed chunk content invalidates the cache,
near-duplicate suppression). Live-verified the cache-hit path against the
real DB (seeded a matching fingerprint, confirmed zero LLM calls; then
confirmed `force=true` does attempt one) since the Groq daily quota was
still exhausted at verification time — a real 429 was also observed live
during this pass and confirmed to surface as the new clean `rate_limited`
error, not a crash.

**Deliberately not done in this pass** (per the written plan, needs more
than one document to validate safely): tightening `retrieval_service.
is_relevant()`'s thresholds or adding rarer-token weighting. Also not
done: smaller-model config split, batching multiple clause types per
call, resume-partial-analysis — all flagged as Tier 2/3 in the plan,
higher complexity/risk, not pursued without further evidence.

## Sprint 6.1.1 — clause-analysis cache integrity hardening

A follow-up to Sprint 6.1's caching mechanism, closing a real integrity
gap found on inspection: the original fingerprint hashed chunk *text*
but not chunk *id*. Reprocessing a document (`ChunkRepository.
replace_for_document`'s delete-then-insert) can produce byte-identical
chunk text under brand-new auto-increment ids — the old fingerprint
would have called that "unchanged" and served a cache hit whose stored
citations pointed at `chunk_id`s no longer present in the `chunks` table.

**Fixed (`app/services/clause_service.py`):**
1. **Fingerprint rebuilt as canonical JSON** (`json.dumps(...,
   sort_keys=True, separators=(",", ":"))`, not `repr()`/string
   concatenation) and now covers: every chunk's `id`, `chunk_index`,
   `char_start`/`char_end`, `section_label`, and `text`; the full clause
   taxonomy (labels + descriptions + search aliases, not just aliases);
   a new explicit `PROMPT_VERSION` marker (`app/prompts/
   clause_detection_prompt.py`, `"v1"`) alongside the raw `SYSTEM_PROMPT`
   text; the configured `llm_provider` name (not just the model string)
   and embedding model; `CHUNKS_PER_ALIAS`/`MAX_CHUNKS_FOR_PROMPT`/
   `NEAR_DUPLICATE_OVERLAP_THRESHOLD`; and all of `retrieval_service`'s
   scoring/relevance constants (`VECTOR_CANDIDATE_POOL`,
   `MAX_EXPECTED_DISTANCE`, `EXACT_PHRASE_BONUS`, `KEYWORD_WEIGHT`,
   `VECTOR_WEIGHT`, `MAX_DISTANCE_FOR_RELEVANCE`,
   `MIN_KEYWORD_SCORE_FOR_RELEVANCE`). Any tuning change to any of these
   now correctly busts the cache instead of silently serving results
   computed under different rules.
2. **`_covers_full_taxonomy()`** — a cache hit now additionally requires
   the cached result set to have exactly one row per `ClauseType` (no
   fewer — an incomplete/partial run — and no more — a duplicate).
3. **`_cached_citations_are_valid()`** — every citation on every
   `present=true` cached row is re-verified against the *current* chunk
   text for its `chunk_id` (reusing `citation_verification.
   quote_appears_in`) before a cache hit is trusted, independent of the
   fingerprint check — defense-in-depth against drift/corruption from any
   source, not just normal reprocessing.
   Any single failure of either check discards the whole cached set and
   falls through to a full fresh run, logged clearly, rather than serving
   a partially-trusted result.

**Tests added (9 new, 34 total passing):** `_covers_full_taxonomy` unit
tests (exact match / duplicate+missing / wrong count), incomplete-cache
triggers a fresh run, a stale citation invalidates a cache hit despite a
genuinely matching fingerprint (seeded independently of any normal
reprocessing path, to test the defensive check in isolation), and — the
core regression this pass exists for — reprocessing that produces the
same chunk text under a *different* chunk_id correctly busts the cache.
Also added `tests/test_http_error_handling.py`: HTTP-level (through the
full FastAPI stack via `TestClient`, not just the service layer) tests
confirming a Groq rate limit surfaces as a real HTTP 429 with the
`rate_limited` error code, an optional `Retry-After` header, and never
leaks raw provider text.

**Verified live** against `agreement_doc1.pdf`: confirmed the old
(pre-hardening) stored fingerprint no longer matches the new formula
(expected — old cached results are correctly treated as stale under the
stricter scheme); confirmed the 20 existing rows do cover the full
taxonomy and their citations still validate against current chunks;
seeded a run under the new fingerprint format and confirmed a genuine
cache hit (zero LLM calls); confirmed changing `MAX_CHUNKS_FOR_PROMPT`
changes the fingerprint.

**Known follow-on note:** the SQLite `chunks` table uses a plain
`INTEGER PRIMARY KEY` (no explicit `AUTOINCREMENT`), so in a
single-document, mostly-empty table, a delete-then-insert *can* reuse a
just-freed id (test fixtures had to route around this explicitly). In
real multi-document production data the table is essentially never
empty, so this isn't a practical production risk — but if `chunk_id`
reuse ever needs to be ruled out categorically, `sqlite_autoincrement`
on `Chunk.__table_args__` is the fix; not applied here since it wasn't
needed for a real observed problem.

**Sprint 7 — COMPLETE.** `POST /documents/{id}/summarize` requires
`status=analyzed` (clear 409 otherwise, pointing at `/analyze-clauses`)
and produces: contract-type classification (`app/core/
contract_taxonomy.py`'s fixed `ContractType` enum — NDA/Employment/
Service/Consulting/Vendor/Lease/Licensing/Partnership/Purchase/
General Business), parties, effective/expiration dates, and key
obligations, all extracted from a small curated chunk set (leading
preamble chunks + chunks already cited by the `parties`/`effective_date`
`ClauseAnalysis` rows — never the whole document), plus a risk rollup.

**Risk counts are computed in code**, not asked of the LLM:
`summary_service._compute_risk_counts()` tallies `ClauseAnalysis.
risk_level` across only `present=true` rows (an absent clause's
risk_level is always "unknown" and would just be noise). Only a short
narrative sentence is LLM-generated from that already-computed breakdown
plus any high-risk clause explanations — the numbers themselves can never
be hallucinated by the narrative call.

Two LLM calls per `/summarize`, with deliberately different failure
behavior: the **extraction** call (contract type/parties/dates) is not
caught — a rate limit propagates as a real 429, consistent with `/ask`
and `/analyze-clauses`, since a "successful but silently empty" summary
would be misleading. The **narrative** call *is* caught (`RateLimitedError`/
`NotImplementedError` only, not arbitrary exceptions) and falls back to a
templated sentence built from the already-solid `risk_counts` — a cheap
prose embellishment isn't worth failing an otherwise-complete summary
over. Extraction citations are verified the same way as everywhere else
(`citation_verification.verify_citations`); zero verified citations means
safe defaults (`general_business`, no parties, no dates), never a
plausible-looking but ungrounded guess.

`ContractSummary` is one row per document (`document_id` unique) updated
in place via `ContractSummaryRepository.upsert()` — no delete-then-insert
needed since there's no multi-row taxonomy to replace, unlike
`ClauseAnalysis`. `GET /documents/{id}/summary` (404 if not yet run) and
`GET /documents/{id}/full-report` (document metadata minus `raw_text` +
summary + all clause analyses in one response) round out the endpoints.

Verified live against `agreement_doc1.pdf`: correctly classified as
`licensing`; parties correctly identified as WPT Enterprises (licensor)
and Zynga Inc/Zynga Game Ireland Limited (licensees); effective date
correctly extracted as "February 1, 2018"; `risk_counts` (`low: 7,
medium: 9, high: 0`) matched the persisted `ClauseAnalysis` data exactly,
confirming the rollup is genuinely code-computed, not LLM-fabricated;
re-running `/summarize` twice left exactly one `contract_summaries` row
(update-in-place, not duplicated); `/summarize` on a document still at
`embedded` status correctly returned a clean 409 pointing at
`/analyze-clauses`.

**All 8 planned sprints are now complete.** Remaining open items are
Sprint 8-style hardening/polish, not new features — see the "Known
limitations" notes throughout this file (no `DELETE /documents/{id}`
yet, no auth/rate limiting, extraction/gate/chunking edge cases are
manually- not automatically-tested, Chroma vector-upsert idempotency has
no automated test, the relevance gate's short-alias weakness is recorded
but not fixed, and the PDF font-encoding artifact is unaddressed).
