"""Shared LLM-response parsing and citation-verification helpers.

Used by both qa_service (Sprint 5) and clause_service (Sprint 6) so the
retrieve -> prompt -> LLM -> parse -> verify-citations pattern doesn't get
duplicated between the two pipelines that both need it: defensive JSON
parsing (tolerating Markdown fences, validating shape) and checking that a
cited quote actually appears verbatim in the chunk it claims to cite.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

_MARKDOWN_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def strip_markdown_fences(text: str) -> str:
    """Some models wrap JSON in a ```json ... ``` fence even when told not
    to. Stripping it costs nothing and protects against a future provider
    swap that doesn't respect JSON-mode as strictly as Groq does."""
    stripped = text.strip()
    match = _MARKDOWN_FENCE_PATTERN.match(stripped)
    return match.group(1).strip() if match else stripped


def parse_llm_json(raw_response: str, *, required_keys: dict[str, type]) -> dict | None:
    """Parses and shape-validates an LLM JSON response.

    `required_keys` maps key name -> expected Python type; every key must
    be present and match its type or this returns None. Returns None (never
    a partially-trusted dict) on any parse or shape failure -- callers must
    treat None as "nothing usable", not fall back to trusting raw text.
    """
    if not isinstance(raw_response, str):
        return None

    try:
        data = json.loads(strip_markdown_fences(raw_response))
    except json.JSONDecodeError:
        logger.warning("Could not parse LLM JSON response: %r", raw_response)
        return None

    if not isinstance(data, dict):
        logger.warning("LLM JSON response was not an object: %r", data)
        return None

    for key, expected_type in required_keys.items():
        if not isinstance(data.get(key), expected_type):
            logger.warning("LLM JSON response missing/invalid key '%s': %r", key, data)
            return None

    return data


def quote_appears_in(quote: str, chunk_text: str) -> bool:
    normalize = lambda s: " ".join(s.split())
    return bool(quote.strip()) and normalize(quote) in normalize(chunk_text)


def verify_citations(raw_citations: list, chunk_text_by_id: dict[int, str]) -> list[dict]:
    """Filters a list of {chunk_id, quote} citation dicts down to only
    those whose quote verifies verbatim (whitespace-normalized) against the
    chunk it claims to cite. Unverifiable citations are dropped, not
    flagged-but-kept -- callers must not trust an LLM's citation blindly."""
    verified = []
    for citation in raw_citations:
        if not isinstance(citation, dict):
            continue
        chunk_id = citation.get("chunk_id")
        quote = citation.get("quote", "")
        chunk_text = chunk_text_by_id.get(chunk_id)
        if chunk_text and isinstance(quote, str) and quote_appears_in(quote, chunk_text):
            verified.append({"chunk_id": chunk_id, "quote": quote})
        else:
            logger.info("Dropping unverifiable citation for chunk_id=%s", chunk_id)
    return verified
