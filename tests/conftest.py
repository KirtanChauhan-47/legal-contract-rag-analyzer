"""Shared pytest fixtures.

Tests use an isolated in-memory SQLite database (StaticPool so the single
connection is shared and content survives across queries within a test) --
never the real legal_rag.db. External services (the embedding model, Chroma,
the Groq API) are monkeypatched per-test rather than exercised for real, so
the suite stays fast and doesn't need network access or an API key.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import chat, chunk, document  # noqa: F401  (register models on Base.metadata)
from app.models.document import Document, DocumentStatus


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_document(db_session, *, filename: str = "test.txt", status: str = DocumentStatus.EMBEDDED.value) -> Document:
    """Creates a minimal Document row directly (bypassing upload/extraction)
    for tests that only need a document to exist at a given status."""
    document = Document(
        original_filename=filename,
        stored_path=f"/tmp/{filename}",
        file_type="txt",
        file_size_bytes=10,
        status=status,
        raw_text="placeholder",
        cleaned_text="placeholder",
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    return document
