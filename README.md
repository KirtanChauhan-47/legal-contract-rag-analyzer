# Legal Contract RAG Analyzer

A backend-first system for uploading legal contracts (PDF/DOCX/TXT) and using
Retrieval-Augmented Generation to answer questions about them, grounded in
cited excerpts from the source document — never free-form LLM guessing about
content it wasn't shown.

> **Not legal advice.** This is an AI-assisted contract *understanding and
> review* tool. It helps locate, summarize, and cite what a contract says —
> it does not interpret legal risk, offer recommendations with legal
> authority, or substitute for review by a qualified attorney.

## Current status

**All 8 planned sprints are complete** (plus 5.1, 6.1, and 6.1.1 hardening
passes). The full pipeline works end-to-end: upload → extract →
gate/clean/chunk → embed → hybrid search → grounded Q&A with citations and
chat history → clause-level detection and risk analysis across a fixed
20-clause taxonomy → contract-type classification, parties/dates
extraction, and a code-computed risk rollup with a short LLM narrative.
What's left is Sprint-8-style hardening/polish (a `DELETE` endpoint, auth,
more automated edge-case tests), not new features — see `CLAUDE.md` for
the full sprint history and known limitations.

## Pipeline

```
upload → extract text (PyMuPDF / python-docx / plain read)
       → contract gate (heuristic + LLM-confirmation for ambiguous cases)
       → clean text (whitespace/hyphenation/quote normalization)
       → chunk (heading-aware, with char_start/char_end offsets)
       → embed (all-MiniLM-L6-v2, stored in ChromaDB)
       → hybrid retrieval (vector similarity + exact-phrase + keyword score)
       → RAG Q&A (Groq LLM, citations verified against source chunks)
       → clause detection (20-clause taxonomy, retrieval-first, grounded)
       → contract summary (type, parties, dates, code-computed risk rollup)
```

Every document moves through an explicit status machine: `uploaded →
extracted → gated_rejected | chunked → embedded → analyzed | failed`. Each
pipeline endpoint checks the current status and fails clearly (409/422) if
called out of order — e.g. you can't `/embed` a document that hasn't been
`/process`ed yet.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | App + DB connectivity check |
| POST | `/documents/upload` | Upload a PDF/DOCX/TXT, extract its text |
| GET | `/documents` | List uploaded documents (paginated) |
| GET | `/documents/{id}` | Fetch one document; `?include_text=true` for full raw text |
| POST | `/documents/{id}/process` | Run the contract gate → clean → chunk pipeline |
| GET | `/documents/{id}/chunks` | Inspect a document's chunks (text, offsets, section labels) |
| POST | `/documents/{id}/embed` | Embed all chunks and upsert into ChromaDB |
| GET | `/documents/{id}/search?q=...` | Debug endpoint: hybrid semantic search, no LLM involved |
| POST | `/documents/{id}/ask` | RAG Q&A — grounded answer with verified citations |
| GET | `/documents/{id}/chat` | Full chat history for a document |
| POST | `/documents/{id}/analyze-clauses?force=false` | Detect and analyze all 20 clause types (retrieval-first, grounded, cached) |
| GET | `/documents/{id}/clauses` | List persisted clause analysis results |
| POST | `/documents/{id}/summarize` | Classify contract type, extract parties/dates, compute risk rollup |
| GET | `/documents/{id}/summary` | Fetch the persisted contract summary |
| GET | `/documents/{id}/full-report` | Document metadata + summary + all clause analyses in one response |

All endpoints are testable directly via Swagger UI at `/docs` — no frontend
exists or is planned for the near term.

## Hybrid retrieval design

Pure vector (embedding) search under-ranks or entirely misses chunks
containing exact legal defined terms — e.g. searching `Allowable
Deductions` against a real licensing agreement returned nothing relevant at
low `top_k`, and ranked the correct chunk as low as #9 at higher `top_k`,
because Chroma only returns its own nearest-by-embedding-distance
candidates, and a verbatim phrase match isn't guaranteed to also be
embedding-close.

To fix this, retrieval (`app/services/retrieval_service.py`, shared by both
`/search` and `/ask`) is hybrid:

1. Pull a wide candidate pool from Chroma (top 20 by vector distance).
2. Separately score **every** chunk in the document (from SQL, the
   authoritative source) for exact-phrase containment and keyword-token
   overlap against the raw query.
3. Combine: `combined_score = (5.0 if exact_phrase_match) + keyword_score +
   vector_similarity`. A verbatim phrase match dominates the ranking
   regardless of what Chroma's distance says — if the query *is* a defined
   term used verbatim in a chunk, that chunk wins.
4. Return the top-k by combined score, with `vector_distance`,
   `keyword_score`, `exact_phrase_match`, `combined_score`, and
   `match_reason` all exposed in the `/search` response so ranking
   decisions are inspectable, not just a bare distance number.

See `CLAUDE.md`'s "Mid-testing fix" section for the full bug writeup and
regression queries used to verify it.

## Grounding and citation safety

- Every `/ask` prompt is built only from retrieved chunks — the full
  document is never sent to the LLM.
- The LLM is instructed to return structured JSON (`{answer, citations}`)
  and cite verbatim quotes; parsing tolerates Markdown code fences and
  validates the response shape before trusting it.
- Every citation's quote is checked against the actual chunk text before
  being returned; unverifiable citations are dropped silently rather than
  passed through.
- If **none** of a model's citations verify, the raw answer text is
  withheld entirely and replaced with an explicit "could not be verified"
  message — an unsupported claim about a legal document is never handed
  back as if it were grounded, even if it sounds confident.
- If retrieval finds nothing relevant (by exact-phrase, keyword, or vector
  distance), the endpoint says so explicitly rather than forcing an answer.
- Chat sessions are scoped to the document they were created for — a
  session UUID from one document is rejected (409) if used against another
  document's `/ask`.

## Clause detection design

`analyze-clauses` checks a fixed 20-clause taxonomy (`app/core/
clause_taxonomy.py`) — confidentiality, termination, governing law,
jurisdiction, payment, limitation of liability, indemnification,
non-compete, non-solicitation, IP, dispute resolution, renewal,
assignment, force majeure, data protection, notices, warranties,
obligations, effective date, and parties. It is **not** 20 unconditional
LLM calls: for each clause type, one or more targeted search-query aliases
retrieve candidate chunks through the same hybrid `retrieval_service.
retrieve()` used by `/search` and `/ask`; the LLM is only called if the
best candidate clears `retrieval_service.is_relevant()` (exact phrase,
strong keyword overlap, or close vector distance). If nothing plausible is
found, the clause is stored `present=false` with no LLM call at all. If
the model claims a clause is present but none of its citations verify
against the retrieved text, the result is stored as absent rather than as
an unsupported finding — the same grounding discipline as `/ask`.

**`risk_level` is a heuristic review signal, not a legal risk assessment.**
It's meant to help a human reviewer decide what to look at closely — it
does not carry legal authority and should not be treated as such.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set:
```
LLM_PROVIDER=groq
GROQ_API_KEY=<your Groq API key>
```
(Get a free key at console.groq.com. Without this, `/ask` and the contract
gate's ambiguous-case LLM confirmation will fail cleanly with a clear error
— everything else in the pipeline works with `LLM_PROVIDER=stub`, the
default.)

## Run

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs for the interactive Swagger UI.

The first request that touches embeddings will download the
`all-MiniLM-L6-v2` model (~90MB) from Hugging Face — this needs internet
access once, then it's cached locally.

## Run the tests

```bash
python -m pytest tests/ -v
```

Tests use an isolated in-memory database and monkeypatch the embedding
model, Chroma, and the LLM provider — they don't need a Groq API key,
network access, or the real `legal_rag.db`.

## Sample workflow

```bash
# 1. Upload a contract
curl -F "file=@resources/sample_nda.txt" http://127.0.0.1:8000/documents/upload
# -> {"id": 1, "status": "extracted", ...}

# 2. Run the contract gate + clean + chunk pipeline
curl -X POST http://127.0.0.1:8000/documents/1/process
# -> {"status": "chunked", "is_legal_contract": true, ...}

# 3. Inspect the chunks (optional, useful for debugging)
curl http://127.0.0.1:8000/documents/1/chunks

# 4. Embed the chunks
curl -X POST http://127.0.0.1:8000/documents/1/embed
# -> {"status": "embedded", ...}

# 5. Try the raw semantic search debug endpoint
curl "http://127.0.0.1:8000/documents/1/search?q=how%20can%20this%20be%20terminated"

# 6. Ask a real grounded question
curl -X POST http://127.0.0.1:8000/documents/1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How can this agreement be terminated?"}'
# -> {"session_id": "...", "answer": "...", "citations": [...]}

# 7. Detect and analyze all 20 clause types
curl -X POST http://127.0.0.1:8000/documents/1/analyze-clauses
# -> [{"clause_type": "termination", "present": true, "risk_level": "medium", ...}, ...]

# 8. Inspect persisted clause results any time afterward
curl http://127.0.0.1:8000/documents/1/clauses

# 9. Classify the contract, extract parties/dates, and roll up risk
curl -X POST http://127.0.0.1:8000/documents/1/summarize
# -> {"contract_type": "...", "parties": [...], "risk_counts": {...}, ...}

# 10. Get everything in one response
curl http://127.0.0.1:8000/documents/1/full-report
```

`resources/` contains sample contracts (and a non-contract text) for
exactly this kind of manual testing — see `resources/README.md`.

## Current limitations

- **Contract gate and chunking are heuristic**, not perfect. The gate is a
  keyword/pattern scorer with LLM confirmation only for ambiguous cases;
  chunk heading detection is regex-based and can occasionally misjudge
  unusual formatting.
- **Retrieval relevance thresholds are empirically tuned**, not
  principled — `MAX_DISTANCE_FOR_RELEVANCE` and
  `MIN_KEYWORD_SCORE_FOR_RELEVANCE` (`app/services/retrieval_service.py`)
  were set by observing real query/document pairs, not derived
  analytically, and may need retuning against more varied documents.
- **PDF text extraction has a known font-encoding artifact** on at least
  one tested document: semicolons render as `Í¾` in extracted text. Cosmetic
  — citation verification still works since the artifact is consistent
  between stored and quoted text — but not fixed.
- **The clause-relevance gate is weaker for short 1–2-word aliases** (e.g.
  `"non-compete"` → tokens `["non", "compete"]`) — a single common-word
  partial match can cross the keyword-overlap threshold on its own,
  meaning the LLM still gets called even when the clause plausibly isn't
  present (the LLM itself then correctly reports it absent, so results
  stay correct, but the cost-saving skip is less effective for these
  clause types than for longer, more specific ones).
- **No auth, rate limiting, Docker, or Alembic migrations** — intentionally
  out of scope for now (see `CLAUDE.md`'s hard guardrails).
- **SQLite is a development database**, not intended for concurrent
  multi-user production use as-is (though models are written to be
  Postgres-portable).
- **Groq's free tier has a daily token quota** — heavy same-day testing
  (e.g. multiple full 20-clause analysis runs) can hit a `429
  rate_limit_exceeded`, which surfaces as a clean HTTP 429 (`rate_limited`,
  with a `Retry-After` header when Groq provides one) rather than a raw
  crash, but does mean `/analyze-clauses`/`/summarize` can temporarily
  fail for reasons outside this app's control. `/analyze-clauses` caches
  its result (see `?force=false`) to avoid re-spending quota on repeated
  calls against an unchanged document.
- **No `DELETE /documents/{id}` endpoint yet** — no way to remove a
  document's SQL rows, Chroma vectors, and uploaded file together
  (Sprint 8 item).

## Project layout

See `CLAUDE.md` for the architecture conventions, module layout, hard
guardrails, and full sprint-by-sprint history this project follows.
