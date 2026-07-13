"""Regression tests for Sprint 5.1 hardening: chat-session document
scoping, citation verification, safe grounding behavior, and defensive
LLM JSON parsing."""
import json

import pytest
from conftest import make_document

from app.core.exceptions import ConflictError
from app.db.chat_repository import ChatSessionRepository
from app.services import qa_service, retrieval_service


def _fake_chunk(chunk_id: int, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "chunk_index": chunk_id,
        "section_label": None,
        "text": text,
        "vector_distance": 0.3,
        "keyword_score": 1.0,
        "exact_phrase_match": True,
        "combined_score": 6.0,
        "match_reason": "exact_phrase",
    }


class _FakeProvider:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def generate(self, prompt, *, system=None):
        return self._response_text


# --- 1. Chat-session document scoping ---------------------------------


def test_session_from_other_document_is_rejected(db_session):
    doc_a = make_document(db_session, filename="a.txt")
    doc_b = make_document(db_session, filename="b.txt")

    session_a = ChatSessionRepository(db_session).create(document_id=doc_a.id)

    with pytest.raises(ConflictError):
        qa_service.ask(db_session, doc_b.id, "some question", session_a.uuid)


def test_session_reused_on_its_own_document_succeeds(db_session, monkeypatch):
    document = make_document(db_session, filename="a.txt")
    session = ChatSessionRepository(db_session).create(document_id=document.id)

    chunk = _fake_chunk(1, "The term is thirty (30) days written notice.")
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [chunk])
    monkeypatch.setattr(
        qa_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "answer": "Thirty days.",
                    "citations": [{"chunk_id": 1, "quote": "thirty (30) days written notice"}],
                }
            )
        ),
    )

    result = qa_service.ask(db_session, document.id, "notice period?", session.uuid)
    assert result["session_id"] == session.uuid


# --- 2. Invalid citation quotes are dropped -----------------------------


def test_invalid_citation_quotes_are_dropped():
    chunks = [_fake_chunk(1, "The term is thirty (30) days written notice.")]
    raw_response = json.dumps(
        {
            "answer": "The notice period is thirty days.",
            "citations": [
                {"chunk_id": 1, "quote": "thirty (30) days written notice"},  # verbatim, valid
                {"chunk_id": 1, "quote": "this exact sentence is never in the document"},  # fabricated
            ],
        }
    )

    answer, verified = qa_service._parse_and_verify(raw_response, chunks)

    assert len(verified) == 1
    assert verified[0]["quote"] == "thirty (30) days written notice"


# --- 3/4. Ungrounded answers are withheld, not returned as confident -----


def test_answer_withheld_when_all_citations_fail(db_session, monkeypatch):
    document = make_document(db_session, filename="c.txt")

    chunk = _fake_chunk(1, "The actual contract text says something completely different.")
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [chunk])
    monkeypatch.setattr(
        qa_service,
        "get_llm_provider",
        lambda: _FakeProvider(
            json.dumps(
                {
                    "answer": "This is a confident-sounding but unverifiable answer.",
                    "citations": [{"chunk_id": 1, "quote": "text that does not appear anywhere in the chunk"}],
                }
            )
        ),
    )

    result = qa_service.ask(db_session, document.id, "some question", None)

    assert result["citations"] == []
    assert result["answer"] == qa_service.UNGROUNDED_ANSWER


def test_unparseable_llm_response_is_withheld_not_passed_through(db_session, monkeypatch):
    document = make_document(db_session, filename="d.txt")

    chunk = _fake_chunk(1, "Some relevant contract text.")
    monkeypatch.setattr(retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [chunk])
    monkeypatch.setattr(qa_service, "get_llm_provider", lambda: _FakeProvider("not valid json at all"))

    result = qa_service.ask(db_session, document.id, "some question", None)

    assert result["citations"] == []
    assert result["answer"] == qa_service.UNGROUNDED_ANSWER


# --- Defensive JSON parsing (Markdown fences, shape validation) ---------


def test_markdown_fenced_json_is_parsed():
    chunks = [_fake_chunk(1, "Governing law is Delaware.")]
    raw_response = (
        '```json\n{"answer": "Delaware law governs.", '
        '"citations": [{"chunk_id": 1, "quote": "Governing law is Delaware."}]}\n```'
    )

    answer, verified = qa_service._parse_and_verify(raw_response, chunks)

    assert answer == "Delaware law governs."
    assert len(verified) == 1


def test_invalid_json_shape_is_rejected():
    chunks = [_fake_chunk(1, "some text")]
    raw_response = json.dumps({"unexpected": "shape"})  # missing "answer"/"citations"

    answer, verified = qa_service._parse_and_verify(raw_response, chunks)

    assert verified == []
