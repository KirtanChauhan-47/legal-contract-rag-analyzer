"""Regression tests: repeated processing/embedding must replace prior
results, never accumulate duplicates (CLAUDE.md hard guardrail #7)."""
from conftest import make_document

from app.db.chunk_repository import ChunkRepository


def _chunk_dict(index: int, text: str) -> dict:
    return {
        "chunk_index": index,
        "text": text,
        "char_start": 0,
        "char_end": len(text),
        "section_label": None,
        "token_count": len(text.split()),
    }


def test_replace_for_document_does_not_duplicate_chunks(db_session):
    document = make_document(db_session, filename="doc.txt", status="chunked")
    repo = ChunkRepository(db_session)

    repo.replace_for_document(document.id, [_chunk_dict(0, "first version chunk a"), _chunk_dict(1, "first version chunk b")])
    db_session.commit()
    assert len(repo.list_by_document(document.id)) == 2

    # Re-processing the same document (e.g. re-running /process) must
    # replace the old chunks, not add to them.
    repo.replace_for_document(document.id, [_chunk_dict(0, "second version chunk only")])
    db_session.commit()

    chunks = repo.list_by_document(document.id)
    assert len(chunks) == 1
    assert chunks[0].text == "second version chunk only"


def test_replace_for_document_is_scoped_per_document(db_session):
    doc_a = make_document(db_session, filename="a.txt", status="chunked")
    doc_b = make_document(db_session, filename="b.txt", status="chunked")
    repo = ChunkRepository(db_session)

    repo.replace_for_document(doc_a.id, [_chunk_dict(0, "doc a chunk")])
    repo.replace_for_document(doc_b.id, [_chunk_dict(0, "doc b chunk one"), _chunk_dict(1, "doc b chunk two")])
    db_session.commit()

    assert len(repo.list_by_document(doc_a.id)) == 1
    assert len(repo.list_by_document(doc_b.id)) == 2

    # Replacing doc_a's chunks must not touch doc_b's.
    repo.replace_for_document(doc_a.id, [])
    db_session.commit()

    assert len(repo.list_by_document(doc_a.id)) == 0
    assert len(repo.list_by_document(doc_b.id)) == 2
