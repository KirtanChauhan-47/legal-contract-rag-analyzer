"""Regression tests for Sprint 6 clause detection: retrieval-first gating
(no LLM call when there's no plausible evidence), citation-grounded
present/absent decisions, idempotent re-analysis, per-document scoping,
and reuse of the existing hybrid retrieval_service."""
import json

import pytest
from conftest import make_document

from app.core.clause_taxonomy import ClauseType
from app.core.exceptions import RateLimitedError
from app.db.analysis_repository import ClauseAnalysisRepository
from app.services import clause_service, retrieval_service


def _relevant_chunk(chunk_id: int = 1, text: str = "Sample relevant contract text.") -> dict:
    return {
        "chunk_id": chunk_id,
        "chunk_index": chunk_id,
        "section_label": "1.",
        "text": text,
        "vector_distance": 0.3,
        "keyword_score": 1.0,
        "exact_phrase_match": True,
        "combined_score": 6.0,
        "match_reason": "exact_phrase",
    }


def _irrelevant_chunk(chunk_id: int = 99) -> dict:
    return {
        "chunk_id": chunk_id,
        "chunk_index": chunk_id,
        "section_label": None,
        "text": "Completely unrelated boilerplate text.",
        "vector_distance": 1.9,
        "keyword_score": 0.0,
        "exact_phrase_match": False,
        "combined_score": 0.05,
        "match_reason": "vector",
    }


class _FakeProvider:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.call_count = 0

    def generate(self, prompt, *, system=None):
        self.call_count += 1
        return self._response_text


def _must_not_be_called_provider():
    def _raise():
        raise AssertionError("LLM should not have been called for a clause with no relevant evidence")

    return _raise


# --- 1. Present clause with a valid citation ----------------------------


def test_present_clause_with_valid_citation(db_session, monkeypatch):
    chunk_text = "The Receiving Party shall keep all Confidential Information secret."
    chunk = _relevant_chunk(text=chunk_text)

    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [chunk])
    monkeypatch.setattr(
        clause_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "present": True,
                    "summary": "Standard confidentiality obligation.",
                    "risk_level": "low",
                    "risk_explanation": "Mutual and standard.",
                    "citations": [{"chunk_id": 1, "quote": chunk_text}],
                }
            )
        ),
    )

    result = clause_service._analyze_one_clause(db_session, document_id=1, clause_type=ClauseType.CONFIDENTIALITY)

    assert result["present"] is True
    assert result["clause_type"] == ClauseType.CONFIDENTIALITY.value
    assert result["risk_level"] == "low"
    assert len(result["citations"]) == 1
    assert result["citations"][0]["quote"] == chunk_text


# --- 2. Absent clause skipped without an LLM call -----------------------


def test_absent_clause_skips_llm_call(db_session, monkeypatch):
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [_irrelevant_chunk()])
    monkeypatch.setattr(clause_service, "get_llm_provider", _must_not_be_called_provider())

    result = clause_service._analyze_one_clause(db_session, document_id=1, clause_type=ClauseType.NON_COMPETE)

    assert result["present"] is False
    assert result["citations"] == []
    assert result["risk_level"] == "unknown"


def test_no_candidates_at_all_skips_llm_call(db_session, monkeypatch):
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [])
    monkeypatch.setattr(clause_service, "get_llm_provider", _must_not_be_called_provider())

    result = clause_service._analyze_one_clause(db_session, document_id=1, clause_type=ClauseType.FORCE_MAJEURE)

    assert result["present"] is False


# --- 3. Claimed-present clause with an invalid citation is downgraded ---


def test_claimed_present_with_invalid_citation_is_downgraded_to_absent(db_session, monkeypatch):
    chunk = _relevant_chunk(text="The actual contract text says something else entirely.")

    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [chunk])
    monkeypatch.setattr(
        clause_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "present": True,
                    "summary": "A fabricated summary.",
                    "risk_level": "high",
                    "risk_explanation": "Fabricated risk claim.",
                    "citations": [{"chunk_id": 1, "quote": "this sentence was never in the document"}],
                }
            )
        ),
    )

    result = clause_service._analyze_one_clause(db_session, document_id=1, clause_type=ClauseType.INDEMNIFICATION)

    assert result["present"] is False
    assert result["citations"] == []
    assert result["summary"] is None


# --- 4. Rerunning analysis replaces results without duplicates ----------


def test_rerunning_analysis_does_not_duplicate_results(db_session, monkeypatch):
    document = make_document(db_session, filename="agreement.txt")

    chunk = _relevant_chunk(text="Governing law is Delaware.")
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [chunk])
    monkeypatch.setattr(
        clause_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "present": True,
                    "summary": "Delaware law governs.",
                    "risk_level": "low",
                    "risk_explanation": None,
                    "citations": [{"chunk_id": 1, "quote": "Governing law is Delaware."}],
                }
            )
        ),
    )

    clause_service.analyze_clauses(db_session, document.id)
    first_count = len(ClauseAnalysisRepository(db_session).list_by_document(document.id))

    # force=True bypasses the Sprint 6.1 result cache so this genuinely
    # re-runs replace_for_document a second time, proving no duplicates.
    clause_service.analyze_clauses(db_session, document.id, force=True)
    second_count = len(ClauseAnalysisRepository(db_session).list_by_document(document.id))

    assert first_count == len(ClauseType)
    assert second_count == len(ClauseType)


# --- 5. Results remain scoped to the correct document -------------------


def test_results_scoped_to_correct_document(db_session, monkeypatch):
    doc_a = make_document(db_session, filename="a.txt")
    doc_b = make_document(db_session, filename="b.txt")

    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [_irrelevant_chunk()])
    monkeypatch.setattr(clause_service, "get_llm_provider", _must_not_be_called_provider())

    clause_service.analyze_clauses(db_session, doc_a.id)
    clause_service.analyze_clauses(db_session, doc_b.id)

    repo = ClauseAnalysisRepository(db_session)
    doc_a_results = repo.list_by_document(doc_a.id)
    doc_b_results = repo.list_by_document(doc_b.id)

    assert len(doc_a_results) == len(ClauseType)
    assert len(doc_b_results) == len(ClauseType)
    assert all(row.document_id == doc_a.id for row in doc_a_results)
    assert all(row.document_id == doc_b.id for row in doc_b_results)


# --- 6. The existing hybrid retrieval path is genuinely reused ----------


def test_clause_detection_reuses_hybrid_retrieval_service(db_session, monkeypatch):
    calls = []

    def _recording_retrieve(db, document_id, query_text, top_k):
        calls.append((document_id, query_text, top_k))
        return [_relevant_chunk()]

    monkeypatch.setattr(retrieval_service, "retrieve", _recording_retrieve)
    monkeypatch.setattr(
        clause_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps({"present": False, "summary": None, "risk_level": "unknown", "risk_explanation": None, "citations": []})
        ),
    )

    clause_service._analyze_one_clause(db_session, document_id=42, clause_type=ClauseType.TERMINATION)

    assert calls, "expected clause_service to call retrieval_service.retrieve at least once"
    assert all(call[0] == 42 for call in calls)


# --- 7. A provider rate-limit failure mid-run does not corrupt results --


class _RateLimitedAfterNCallsProvider:
    """Simulates hitting Groq's rate limit partway through a 20-clause run."""

    def __init__(self, fail_after: int):
        self._fail_after = fail_after
        self.calls = 0

    def generate(self, prompt, *, system=None):
        self.calls += 1
        if self.calls > self._fail_after:
            raise RateLimitedError("Groq rate limit reached (simulated)", retry_after_seconds=30)
        return json.dumps(
            {"present": False, "summary": None, "risk_level": "unknown", "risk_explanation": None, "citations": []}
        )


def test_rate_limit_during_analysis_does_not_corrupt_existing_results(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt")

    # Seed prior results as if a previous successful run already completed.
    prior_results = [
        {
            "clause_type": clause_type.value,
            "present": False,
            "summary": None,
            "risk_level": "unknown",
            "risk_explanation": None,
            "citations": [],
        }
        for clause_type in ClauseType
    ]
    repo = ClauseAnalysisRepository(db_session)
    repo.replace_for_document(document.id, prior_results)
    db_session.commit()

    # A single shared provider instance -- its call counter must persist
    # across every clause type in the run, not reset per call.
    flaky_provider = _RateLimitedAfterNCallsProvider(fail_after=3)
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [_relevant_chunk()])
    monkeypatch.setattr(clause_service, "get_llm_provider", lambda: flaky_provider)

    with pytest.raises(RateLimitedError):
        clause_service.analyze_clauses(db_session, document.id)

    # The whole result list is built in memory before replace_for_document
    # is ever called -- a mid-run failure must leave prior rows untouched,
    # not partially overwritten or duplicated.
    rows_after_failure = repo.list_by_document(document.id)
    assert len(rows_after_failure) == len(ClauseType)
    assert {row.clause_type for row in rows_after_failure} == {ct.value for ct in ClauseType}


# --- 8. Sprint 6.1: analysis caching (fingerprint-based skip) -----------


class _CountingProvider:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.call_count = 0

    def generate(self, prompt, *, system=None):
        self.call_count += 1
        return self._response_text


def _seed_one_real_chunk(db_session, document_id: int, text: str) -> None:
    from app.db.chunk_repository import ChunkRepository

    ChunkRepository(db_session).replace_for_document(
        document_id,
        [{"chunk_index": 0, "text": text, "char_start": 0, "char_end": len(text), "section_label": None, "token_count": len(text.split())}],
    )
    db_session.commit()


def test_unchanged_rerun_skips_llm_calls_by_default(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt")
    _seed_one_real_chunk(db_session, document.id, "Governing law is Delaware.")

    chunk = _relevant_chunk(text="Governing law is Delaware.")
    provider = _CountingProvider(
        json.dumps(
            {
                "present": True,
                "summary": "Delaware law governs.",
                "risk_level": "low",
                "risk_explanation": None,
                "citations": [{"chunk_id": 1, "quote": "Governing law is Delaware."}],
            }
        )
    )
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [chunk])
    monkeypatch.setattr(clause_service, "get_llm_provider", lambda: provider)

    clause_service.analyze_clauses(db_session, document.id)
    calls_after_first_run = provider.call_count
    assert calls_after_first_run > 0

    clause_service.analyze_clauses(db_session, document.id)  # force=False (default), nothing changed
    assert provider.call_count == calls_after_first_run, "expected zero additional LLM calls on an unchanged rerun"


def test_force_true_bypasses_the_cache(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt")
    _seed_one_real_chunk(db_session, document.id, "Governing law is Delaware.")

    chunk = _relevant_chunk(text="Governing law is Delaware.")
    provider = _CountingProvider(
        json.dumps(
            {
                "present": True,
                "summary": "Delaware law governs.",
                "risk_level": "low",
                "risk_explanation": None,
                "citations": [{"chunk_id": 1, "quote": "Governing law is Delaware."}],
            }
        )
    )
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [chunk])
    monkeypatch.setattr(clause_service, "get_llm_provider", lambda: provider)

    clause_service.analyze_clauses(db_session, document.id)
    calls_after_first_run = provider.call_count

    clause_service.analyze_clauses(db_session, document.id, force=True)
    assert provider.call_count > calls_after_first_run, "expected force=True to re-call the LLM despite an unchanged fingerprint"


def test_changed_chunks_invalidate_the_cache(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt")
    _seed_one_real_chunk(db_session, document.id, "Governing law is Delaware.")

    provider = _CountingProvider(
        json.dumps(
            {"present": True, "summary": "s", "risk_level": "low", "risk_explanation": None, "citations": [{"chunk_id": 1, "quote": "x"}]}
        )
    )
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [_relevant_chunk(text="x")])
    monkeypatch.setattr(clause_service, "get_llm_provider", lambda: provider)

    clause_service.analyze_clauses(db_session, document.id)
    calls_after_first_run = provider.call_count

    # Re-process the document with different chunk text -- the fingerprint
    # must change, so the next analysis must NOT be served from cache.
    _seed_one_real_chunk(db_session, document.id, "Completely different clause text now.")

    clause_service.analyze_clauses(db_session, document.id)  # still force=False
    assert provider.call_count > calls_after_first_run, "expected changed chunk content to invalidate the cache"


# --- 9. Sprint 6.1: near-duplicate chunk suppression --------------------


def test_near_duplicate_candidate_chunks_are_not_both_sent_to_the_prompt():
    identical_text = "This Agreement will for all purposes be governed by the laws of the State of California."
    candidates = [
        {**_relevant_chunk(chunk_id=60, text=identical_text), "combined_score": 6.0},
        {**_relevant_chunk(chunk_id=61, text=identical_text), "combined_score": 5.9},
        {**_relevant_chunk(chunk_id=99, text="A totally different clause about indemnification obligations."), "combined_score": 5.5},
    ]

    selected = clause_service._select_prompt_chunks(candidates, max_chunks=3)

    selected_ids = [c["chunk_id"] for c in selected]
    assert 60 in selected_ids
    assert 61 not in selected_ids, "near-duplicate of chunk 60 should have been skipped"
    assert 99 in selected_ids
