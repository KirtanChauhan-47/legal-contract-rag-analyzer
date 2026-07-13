"""Regression tests for Sprint 6.1: Groq rate-limit errors must surface as
a clean 429 (RateLimitedError), never a generic 500, and must not leak raw
provider internals (org IDs, raw error bodies) to the client."""
import httpx
import pytest
from groq import RateLimitError

from app.core.exceptions import RateLimitedError as AppRateLimitedError
from app.services.llm_service import GroqLLMProvider


def _make_groq_rate_limit_error(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, headers=headers, request=request)
    return RateLimitError(
        "Error code: 429 - {'error': {'message': 'Rate limit reached ... org_secret123', "
        "'type': 'tokens', 'code': 'rate_limit_exceeded'}}",
        response=response,
        body=None,
    )


class _FakeGroqClientThatRateLimits:
    class _Completions:
        def __init__(self, error):
            self._error = error

        def create(self, **kwargs):
            raise self._error

    class _Chat:
        def __init__(self, error):
            self.completions = _FakeGroqClientThatRateLimits._Completions(error)

    def __init__(self, error):
        self.chat = _FakeGroqClientThatRateLimits._Chat(error)


def test_groq_rate_limit_is_mapped_to_app_rate_limited_error(monkeypatch):
    provider = GroqLLMProvider(api_key="fake", model="fake-model")
    provider._client = _FakeGroqClientThatRateLimits(_make_groq_rate_limit_error(retry_after="42"))

    with pytest.raises(AppRateLimitedError) as exc_info:
        provider.generate("some prompt", system="some system prompt")

    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 42
    # The raw provider message (which can contain org identifiers) must
    # never be relayed verbatim to the client.
    assert "org_secret123" not in exc_info.value.message


def test_groq_rate_limit_without_retry_after_header_still_maps_cleanly():
    provider = GroqLLMProvider(api_key="fake", model="fake-model")
    provider._client = _FakeGroqClientThatRateLimits(_make_groq_rate_limit_error(retry_after=None))

    with pytest.raises(AppRateLimitedError) as exc_info:
        provider.generate("some prompt")

    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds is None
