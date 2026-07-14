"""Regression tests for Sprint 7 contract summary: status precondition,
grounded extraction (citation-verified or safe defaults), risk counts
computed in code (not LLM), narrative fallback when the LLM is
unavailable, idempotent re-summarization, and full-report assembly."""
import json

import pytest
from conftest import make_document

from app.core.clause_taxonomy import ClauseType
from app.core.exceptions import ConflictError, NotFoundError, RateLimitedError
from app.db.analysis_repository import ClauseAnalysisRepository, ContractSummaryRepository
from app.db.chunk_repository import ChunkRepository
from app.services import summary_service


def _chunk_dict(index: int, text: str, section_label: str | None = None) -> dict:
    return {
        "chunk_index": index,
        "text": text,
        "char_start": 0,
        "char_end": len(text),
        "section_label": section_label,
        "token_count": len(text.split()),
    }


def _clause_row(clause_type: str, *, present: bool, risk_level: str = "unknown", risk_explanation=None, citations=None):
    return {
        "clause_type": clause_type,
        "present": present,
        "summary": "s" if present else None,
        "risk_level": risk_level,
        "risk_explanation": risk_explanation,
        "citations": citations or [],
    }


def _full_taxonomy_rows(overrides: dict[str, dict] | None = None) -> list[dict]:
    """One absent row per ClauseType (i.e. a complete, valid clause
    analysis), with any per-clause-type overrides layered on top."""
    overrides = overrides or {}
    rows = []
    for clause_type in ClauseType:
        row = _clause_row(clause_type.value, present=False)
        row.update(overrides.get(clause_type.value, {}))
        rows.append(row)
    return rows


class _FakeProvider:
    def __init__(self, response_text: str):
        self._response_text = response_text
        self.call_count = 0

    def generate(self, prompt, *, system=None):
        self.call_count += 1
        return self._response_text


class _RateLimitedProvider:
    def generate(self, prompt, *, system=None):
        raise RateLimitedError("rate limited", retry_after_seconds=30)


def test_summarize_requires_analyzed_status(db_session):
    document = make_document(db_session, filename="doc.txt", status="embedded")

    with pytest.raises(ConflictError):
        summary_service.summarize(db_session, document.id)


def test_summarize_requires_clause_analysis_results(db_session):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    # status=analyzed but no ClauseAnalysis rows persisted -- shouldn't happen
    # via the normal flow, but the service must reject it explicitly rather
    # than silently summarizing nothing.
    with pytest.raises(ConflictError):
        summary_service.summarize(db_session, document.id)


def test_summarize_extracts_details_with_valid_citation(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(
        document.id,
        [_chunk_dict(0, "This Agreement is entered into by Acme Corp and Beta LLC.", "preamble")],
    )
    db_session.commit()
    chunk = ChunkRepository(db_session).list_by_document(document.id)[0]

    rows = _full_taxonomy_rows(
        {"parties": {"present": True, "citations": [{"chunk_id": chunk.id, "quote": "Acme Corp and Beta LLC"}]}}
    )
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(
        summary_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "contract_type": "service",
                    "parties": [{"name": "Acme Corp", "role": "Provider"}, {"name": "Beta LLC", "role": "Client"}],
                    "effective_date": "January 1, 2026",
                    "expiration_date": None,
                    "key_obligations": [],
                    "citations": [{"chunk_id": chunk.id, "quote": "This Agreement is entered into by Acme Corp and Beta LLC."}],
                }
            )
        ),
    )

    summary = summary_service.summarize(db_session, document.id)

    assert summary.contract_type == "service"
    assert len(summary.parties) == 2
    assert summary.effective_date == "January 1, 2026"


def test_summarize_falls_back_to_defaults_when_extraction_citations_invalid(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(document.id, [_chunk_dict(0, "Actual preamble text.", "preamble")])
    db_session.commit()

    rows = _full_taxonomy_rows()
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(
        summary_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "contract_type": "nda",
                    "parties": [{"name": "Fabricated Party", "role": None}],
                    "effective_date": "made up date",
                    "expiration_date": None,
                    "key_obligations": [],
                    "citations": [{"chunk_id": 999, "quote": "text that does not appear anywhere"}],
                }
            )
        ),
    )

    summary = summary_service.summarize(db_session, document.id)

    assert summary.contract_type == "general_business"
    assert summary.parties == []
    assert summary.effective_date is None


def test_risk_counts_are_computed_in_code_not_from_llm(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(document.id, [_chunk_dict(0, "text", "1.")])
    db_session.commit()

    rows = _full_taxonomy_rows(
        {
            "termination": {"present": True, "risk_level": "high", "risk_explanation": "Onerous notice terms."},
            "payment": {"present": True, "risk_level": "medium"},
            "notices": {"present": True, "risk_level": "low"},
            "parties": {"present": True, "risk_level": "low"},
            # non_compete stays absent (the default) -- must not pollute risk_counts
        }
    )
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    # The narrative LLM call is instructed not to alter the counts -- but
    # even if it tried to, risk_counts is computed before the call and
    # never derived from the LLM's response.
    monkeypatch.setattr(summary_service, "get_llm_provider", lambda: _FakeProvider(json.dumps({"narrative": "All good."})))

    summary = summary_service.summarize(db_session, document.id)

    assert summary.risk_counts == {"high": 1, "medium": 1, "low": 2, "unknown": 0}


def test_narrative_falls_back_when_llm_unavailable(db_session, monkeypatch):
    # Deliberately no chunks at all: _gather_extraction_chunks returns [],
    # so _extract_contract_details short-circuits to safe defaults without
    # ever calling the (rate-limited) provider. This isolates the narrative
    # step, which is the one that's supposed to degrade gracefully --
    # extraction failures are meant to propagate as a real 429 instead (see
    # test_summarize_propagates_rate_limit_from_extraction below).
    document = make_document(db_session, filename="doc.txt", status="analyzed")

    rows = _full_taxonomy_rows(
        {"termination": {"present": True, "risk_level": "high", "risk_explanation": "Risky."}}
    )
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(summary_service, "get_llm_provider", lambda: _RateLimitedProvider())

    summary = summary_service.summarize(db_session, document.id)

    assert "1 high-risk" in summary.risk_summary_narrative
    assert summary.contract_type == "general_business"  # no chunks tagged for extraction -> safe defaults


def test_summarize_propagates_rate_limit_from_extraction(db_session, monkeypatch):
    # Unlike the narrative step, the primary extraction call is NOT
    # swallowed -- a rate limit there must surface as a real error to the
    # caller (eventually a 429), consistent with /ask and /analyze-clauses,
    # rather than silently degrading to a "successful" but empty summary.
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(document.id, [_chunk_dict(0, "Some preamble text.", "preamble")])
    db_session.commit()

    rows = _full_taxonomy_rows({"termination": {"present": True, "risk_level": "low"}})
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(summary_service, "get_llm_provider", lambda: _RateLimitedProvider())

    with pytest.raises(RateLimitedError):
        summary_service.summarize(db_session, document.id)


def test_rerunning_summarize_updates_in_place_not_duplicated(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(document.id, [_chunk_dict(0, "text", "1.")])
    db_session.commit()

    rows = _full_taxonomy_rows({"termination": {"present": True, "risk_level": "low"}})
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(summary_service, "get_llm_provider", lambda: _FakeProvider(json.dumps({"narrative": "First."})))
    summary_service.summarize(db_session, document.id)

    monkeypatch.setattr(summary_service, "get_llm_provider", lambda: _FakeProvider(json.dumps({"narrative": "Second."})))
    summary_service.summarize(db_session, document.id)

    all_summaries = (
        db_session.query(ContractSummaryRepository(db_session).model)
        .filter_by(document_id=document.id)
        .all()
    )
    assert len(all_summaries) == 1
    assert all_summaries[0].risk_summary_narrative == "Second."


def test_get_summary_raises_not_found_before_summarize(db_session):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    with pytest.raises(NotFoundError):
        summary_service.get_summary(db_session, document.id)


def test_get_full_report_combines_document_summary_and_clauses(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(document.id, [_chunk_dict(0, "text", "1.")])
    db_session.commit()

    rows = _full_taxonomy_rows({"termination": {"present": True, "risk_level": "low"}})
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(summary_service, "get_llm_provider", lambda: _FakeProvider(json.dumps({"narrative": "n"})))
    summary_service.summarize(db_session, document.id)

    report = summary_service.get_full_report(db_session, document.id)

    assert report["document"].id == document.id
    assert report["summary"] is not None
    assert len(report["clauses"]) == len(ClauseType)


def test_incomplete_clause_analysis_returns_conflict(db_session):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    # Only 2 of the 20 ClauseType rows exist -- e.g. an interrupted or
    # corrupted analyze-clauses run -- must be rejected, not silently
    # summarized from a partial picture.
    ClauseAnalysisRepository(db_session).replace_for_document(
        document.id,
        [
            _clause_row(ClauseType.TERMINATION.value, present=True, risk_level="low"),
            _clause_row(ClauseType.PAYMENT.value, present=False),
        ],
    )
    db_session.commit()

    with pytest.raises(ConflictError):
        summary_service.summarize(db_session, document.id)


class _FakeRow:
    """Minimal stand-in for a ClauseAnalysis row -- only .clause_type is
    needed to exercise _covers_full_taxonomy as a pure function. (A real
    duplicate document_id+clause_type row can't be persisted at all, since
    ClauseAnalysis has a UNIQUE constraint on that pair -- this checks the
    defense-in-depth logic directly, same pattern as clause_service's own
    _covers_full_taxonomy tests.)"""

    def __init__(self, clause_type: str):
        self.clause_type = clause_type


def test_covers_full_taxonomy_rejects_duplicate_and_missing_clause_types():
    clause_values = [ct.value for ct in ClauseType if ct != ClauseType.PARTIES]
    clause_values.append(ClauseType.TERMINATION.value)
    rows = [_FakeRow(value) for value in clause_values]

    assert len(rows) == len(ClauseType)  # right count, wrong set
    assert summary_service._covers_full_taxonomy(rows) is False


def test_covers_full_taxonomy_accepts_exactly_one_row_per_clause_type():
    rows = [_FakeRow(ct.value) for ct in ClauseType]
    assert summary_service._covers_full_taxonomy(rows) is True


def test_complete_clause_analysis_still_succeeds(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    rows = _full_taxonomy_rows(
        {ClauseType.TERMINATION.value: {"present": True, "risk_level": "low", "summary": "s"}}
    )
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(summary_service, "get_llm_provider", lambda: _FakeProvider(json.dumps({"narrative": "ok"})))

    summary = summary_service.summarize(db_session, document.id)

    assert summary.risk_summary_narrative == "ok"
    assert summary.risk_counts["low"] == 1


def test_summarize_persists_verified_citations(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(
        document.id,
        [_chunk_dict(0, "This Agreement is entered into by Acme Corp and Beta LLC.", "preamble")],
    )
    db_session.commit()
    chunk = ChunkRepository(db_session).list_by_document(document.id)[0]

    rows = _full_taxonomy_rows(
        {
            ClauseType.PARTIES.value: {
                "present": True,
                "citations": [{"chunk_id": chunk.id, "quote": "Acme Corp and Beta LLC"}],
            }
        }
    )
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(
        summary_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "contract_type": "service",
                    "parties": [{"name": "Acme Corp", "role": "Provider"}],
                    "effective_date": None,
                    "expiration_date": None,
                    "key_obligations": [],
                    "citations": [
                        {"chunk_id": chunk.id, "quote": "This Agreement is entered into by Acme Corp and Beta LLC."}
                    ],
                }
            )
        ),
    )

    summary = summary_service.summarize(db_session, document.id)

    assert summary.citations == [
        {"chunk_id": chunk.id, "quote": "This Agreement is entered into by Acme Corp and Beta LLC."}
    ]


def test_summarize_stores_no_citations_when_none_verify(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(document.id, [_chunk_dict(0, "Actual preamble text.", "preamble")])
    db_session.commit()

    rows = _full_taxonomy_rows()
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(
        summary_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "contract_type": "nda",
                    "parties": [],
                    "effective_date": None,
                    "expiration_date": None,
                    "key_obligations": [],
                    "citations": [{"chunk_id": 999, "quote": "does not appear anywhere"}],
                }
            )
        ),
    )

    summary = summary_service.summarize(db_session, document.id)

    assert summary.citations == []


def test_summary_read_schema_includes_citations(db_session, monkeypatch):
    from app.schemas.summary import ContractSummaryRead

    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(
        document.id, [_chunk_dict(0, "This Agreement is between Acme Corp and Beta LLC.", "preamble")]
    )
    db_session.commit()
    chunk = ChunkRepository(db_session).list_by_document(document.id)[0]

    rows = _full_taxonomy_rows()
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(
        summary_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "contract_type": "nda",
                    "parties": [],
                    "effective_date": None,
                    "expiration_date": None,
                    "key_obligations": [],
                    "citations": [{"chunk_id": chunk.id, "quote": "This Agreement is between Acme Corp and Beta LLC."}],
                }
            )
        ),
    )

    summary_service.summarize(db_session, document.id)
    summary = summary_service.get_summary(db_session, document.id)

    schema = ContractSummaryRead.model_validate(summary)
    assert len(schema.citations) == 1
    assert schema.citations[0].chunk_id == chunk.id


def test_full_report_includes_summary_citations(db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt", status="analyzed")
    ChunkRepository(db_session).replace_for_document(
        document.id, [_chunk_dict(0, "This Agreement is between Acme Corp and Beta LLC.", "preamble")]
    )
    db_session.commit()
    chunk = ChunkRepository(db_session).list_by_document(document.id)[0]

    rows = _full_taxonomy_rows()
    ClauseAnalysisRepository(db_session).replace_for_document(document.id, rows)
    db_session.commit()

    monkeypatch.setattr(
        summary_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "contract_type": "nda",
                    "parties": [],
                    "effective_date": None,
                    "expiration_date": None,
                    "key_obligations": [],
                    "citations": [{"chunk_id": chunk.id, "quote": "This Agreement is between Acme Corp and Beta LLC."}],
                }
            )
        ),
    )

    summary_service.summarize(db_session, document.id)
    report = summary_service.get_full_report(db_session, document.id)

    assert report["summary"].citations == [
        {"chunk_id": chunk.id, "quote": "This Agreement is between Acme Corp and Beta LLC."}
    ]
