"""LLM provider abstraction.

Every other service depends on the `LLMProvider` interface only, never a
provider SDK directly, so the underlying model can be swapped (Groq ->
Gemini/OpenAI) without touching business logic.
"""
import abc

from app.core.config import get_settings


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a text completion for the given prompt."""
        raise NotImplementedError


class StubLLMProvider(LLMProvider):
    """Placeholder provider used when no real LLM is configured.

    Raising here (rather than returning canned text) makes it obvious at
    call time if something tries to use LLM generation before it's set up.
    """

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        raise NotImplementedError(
            "LLM generation is not wired up (LLM_PROVIDER=stub). Set "
            "LLM_PROVIDER=groq and GROQ_API_KEY in .env to use real generation."
        )


class GroqLLMProvider(LLMProvider):
    """Real Groq-backed provider. The groq SDK is imported only here, never
    at module level elsewhere, keeping the rest of the app provider-agnostic."""

    def __init__(self, api_key: str, model: str):
        from groq import Groq

        self._client = Groq(api_key=api_key)
        self._model = model

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content


def get_llm_provider() -> LLMProvider:
    """Factory selecting the configured provider via LLM_PROVIDER."""
    settings = get_settings()
    if settings.llm_provider == "stub":
        return StubLLMProvider()
    if settings.llm_provider == "groq":
        return GroqLLMProvider(api_key=settings.groq_api_key, model=settings.groq_model)
    raise NotImplementedError(f"LLM provider '{settings.llm_provider}' is not implemented yet.")
