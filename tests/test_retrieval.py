"""Regression test for the Sprint 5.1 retrieval-quality fix: an exact legal
defined-term phrase match must rank at the top even when the (mocked) vector
signal contributes nothing -- this is the failure mode found during manual
testing with a real licensing agreement (see CLAUDE.md's "Mid-testing fix"
section)."""
from conftest import make_document

from app.db.chunk_repository import ChunkRepository
from app.services import embedding_service, retrieval_service, vector_store_service


def test_exact_phrase_ranks_top(db_session, monkeypatch):
    document = make_document(db_session, filename="agreement.txt")

    ChunkRepository(db_session).replace_for_document(
        document.id,
        [
            {
                "chunk_index": 0,
                "text": "BASIC PROVISIONS. This agreement is between the parties.",
                "char_start": 0,
                "char_end": 57,
                "section_label": "BASIC PROVISIONS",
                "token_count": 8,
            },
            {
                "chunk_index": 1,
                "text": (
                    '"Net Revenue" shall be defined as gross revenues less the following '
                    'actual and verifiable "Allowable Deductions": (i) payment processing '
                    "fees, (ii) governmental taxes, and (iii) chargebacks/refunds."
                ),
                "char_start": 57,
                "char_end": 250,
                "section_label": "3.",
                "token_count": 25,
            },
            {
                "chunk_index": 2,
                "text": "INDEMNIFICATION. Each party shall indemnify and hold harmless the other party.",
                "char_start": 250,
                "char_end": 330,
                "section_label": "INDEMNIFICATION",
                "token_count": 10,
            },
        ],
    )
    db_session.commit()

    # Isolate the hybrid-scoring logic under test: no real embedding model,
    # no real Chroma -- the vector signal contributes literally nothing, so
    # a passing test proves the exact-phrase path alone is sufficient.
    monkeypatch.setattr(embedding_service, "embed_texts", lambda texts: [[0.0, 0.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store_service, "query", lambda document_id, query_embedding, top_k: [])

    results = retrieval_service.retrieve(db_session, document.id, "Allowable Deductions", top_k=3)

    assert results, "expected at least one candidate"
    assert results[0]["exact_phrase_match"] is True
    assert "Allowable Deductions" in results[0]["text"]
    assert results[0]["vector_distance"] is None  # confirms it wasn't the vector signal that ranked it


def test_irrelevant_query_does_not_surface_exact_phrase_match(db_session, monkeypatch):
    document = make_document(db_session, filename="agreement2.txt")

    ChunkRepository(db_session).replace_for_document(
        document.id,
        [
            {
                "chunk_index": 0,
                "text": "GOVERNING LAW. This Agreement is governed by the laws of Delaware.",
                "char_start": 0,
                "char_end": 68,
                "section_label": "GOVERNING LAW",
                "token_count": 10,
            },
        ],
    )
    db_session.commit()

    monkeypatch.setattr(embedding_service, "embed_texts", lambda texts: [[0.0, 0.0, 0.0] for _ in texts])
    monkeypatch.setattr(vector_store_service, "query", lambda document_id, query_embedding, top_k: [])

    results = retrieval_service.retrieve(db_session, document.id, "unrelated tomato gardening tips", top_k=3)

    assert results == []
