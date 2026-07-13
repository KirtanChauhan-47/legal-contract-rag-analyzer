"""HTTP-level tests: confirm exceptions actually surface through the full
FastAPI stack (router -> dependency injection -> service -> exception
handler middleware) with the right status code, body shape, and headers --
not just verified at the service layer, which the existing
test_llm_service.py tests already cover."""
import pytest
from conftest import make_document
from fastapi.testclient import TestClient

from app.core.exceptions import RateLimitedError
from app.db.session import get_db
from app.main import app
from app.services import qa_service


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    # No `with TestClient(app) as client:` -- that would trigger the
    # startup lifespan event (init_db() against the REAL configured
    # database), which tests must never touch.
    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


class _RateLimitedProvider:
    def __init__(self, retry_after_seconds: int | None = None):
        self._retry_after_seconds = retry_after_seconds

    def generate(self, prompt, *, system=None):
        raise RateLimitedError(
            "The configured LLM provider's rate limit was reached. Please retry later, "
            "or configure a different provider/model.",
            retry_after_seconds=self._retry_after_seconds,
        )


def _relevant_chunk() -> dict:
    return {
        "chunk_id": 1,
        "chunk_index": 0,
        "section_label": "1.",
        "text": "Some relevant contract text.",
        "vector_distance": 0.3,
        "keyword_score": 1.0,
        "exact_phrase_match": True,
        "combined_score": 6.0,
        "match_reason": "exact_phrase",
    }


def test_groq_rate_limit_surfaces_as_http_429_on_ask(client, db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt")

    monkeypatch.setattr(qa_service.retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [_relevant_chunk()])
    monkeypatch.setattr(qa_service, "get_llm_provider", lambda: _RateLimitedProvider(retry_after_seconds=17))

    response = client.post(f"/documents/{document.id}/ask", json={"question": "What is the notice period?"})

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "rate_limited"
    assert "message" in body["error"]
    assert response.headers.get("retry-after") == "17"


def test_groq_rate_limit_without_retry_after_still_returns_429(client, db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt")

    monkeypatch.setattr(qa_service.retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [_relevant_chunk()])
    monkeypatch.setattr(qa_service, "get_llm_provider", lambda: _RateLimitedProvider(retry_after_seconds=None))

    response = client.post(f"/documents/{document.id}/ask", json={"question": "What is the notice period?"})

    assert response.status_code == 429
    assert "retry-after" not in {key.lower() for key in response.headers.keys()}


def test_rate_limited_response_never_leaks_raw_provider_text(client, db_session, monkeypatch):
    document = make_document(db_session, filename="doc.txt")

    monkeypatch.setattr(qa_service.retrieval_service, "retrieve", lambda db, doc_id, q, top_k: [_relevant_chunk()])
    monkeypatch.setattr(qa_service, "get_llm_provider", lambda: _RateLimitedProvider(retry_after_seconds=5))

    response = client.post(f"/documents/{document.id}/ask", json={"question": "test"})

    # The safe, app-authored message only -- never a raw provider error body.
    assert "org_" not in response.text
    assert "rate_limit_exceeded" not in response.text
