"""LLM provider abstraction.

No concrete provider (Groq/Gemini/OpenAI) is wired in yet — that happens in
the RAG/Q&A sprint. Every other service must depend on the `LLMProvider`
interface only, never import a provider SDK directly, so the underlying
model can be swapped without touching business logic.
"""
import abc

from app.core.config import get_settings


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a text completion for the given prompt."""
        raise NotImplementedError


class StubLLMProvider(LLMProvider):
    """Placeholder provider used until real LLM integration lands.

    Raising here (rather than returning canned text) makes it obvious at
    call time if something tries to use LLM generation before it exists.
    """

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        raise NotImplementedError(
            "LLM generation is not wired up yet (Sprint 1 scaffolding only). "
            "Real provider integration (Groq) lands in the RAG/Q&A sprint."
        )


def get_llm_provider() -> LLMProvider:
    """Factory selecting the configured provider.

    Only 'stub' is implemented today; 'groq'/'gemini'/'openai' will be added
    as concrete LLMProvider subclasses behind this same factory later.
    """
    settings = get_settings()
    if settings.llm_provider == "stub":
        return StubLLMProvider()
    raise NotImplementedError(f"LLM provider '{settings.llm_provider}' is not implemented yet.")
