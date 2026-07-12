"""Decides whether an uploaded document is actually a legal contract, before
it's ever chunked/embedded/analyzed. Two tiers, cheapest first:

1. Heuristic pre-filter (free, instant): score how many contract-signal
   patterns appear in the text. Confident accepts/rejects stop here.
2. LLM confirmation (only for ambiguous scores, and only on a short excerpt
   — never the full document): asks the configured LLMProvider to judge.

Real LLM wiring (Groq) lands in a later sprint; until then, get_llm_provider()
returns a stub that raises NotImplementedError, and ambiguous cases fall
back to a heuristic-only decision. No code here needs to change when Groq
is wired up — it'll just start being called instead of raising.
"""
import json
import logging
import re

from app.prompts.contract_gate_prompt import build_gate_prompt
from app.services.llm_service import get_llm_provider

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 200
ACCEPT_THRESHOLD = 5
REJECT_THRESHOLD = 2
EXCERPT_CHARS_FOR_LLM = 4000

SIGNAL_PATTERNS = [
    r"\bagreement\b",
    r"\bwhereas\b",
    r"\bhereby\b",
    r"\bshall\b",
    r"\bparties\b",
    r"\bparty\b",
    r"\bgoverning law\b",
    r"\beffective date\b",
    r"\btermination\b",
    r"\bconfidential",
    r"\bindemnif",
    r"\bliability\b",
    r"\bsignature\b",
    r"\b(?:section|article)\s+\d+",
    r"^\s*\d+\.\s+[A-Z]",
]


class GateResult:
    def __init__(self, is_contract: bool, reason: str, contract_type: str | None = None):
        self.is_contract = is_contract
        self.reason = reason
        self.contract_type = contract_type


def _heuristic_score(text: str) -> int:
    return sum(1 for pattern in SIGNAL_PATTERNS if re.search(pattern, text, re.IGNORECASE | re.MULTILINE))


def run_gate(text: str) -> GateResult:
    if len(text.strip()) < MIN_TEXT_LENGTH:
        return GateResult(False, "Document text is too short to plausibly be a contract.")

    score = _heuristic_score(text)

    if score >= ACCEPT_THRESHOLD:
        return GateResult(True, f"Heuristic pre-filter matched {score} contract signal(s).")
    if score <= REJECT_THRESHOLD:
        return GateResult(False, f"Heuristic pre-filter matched only {score} contract signal(s).")

    return _confirm_with_llm(text, score)


def _confirm_with_llm(text: str, heuristic_score: int) -> GateResult:
    excerpt = text[:EXCERPT_CHARS_FOR_LLM]
    try:
        provider = get_llm_provider()
        raw_response = provider.generate(build_gate_prompt(excerpt))
        return _parse_llm_response(raw_response)
    except NotImplementedError:
        accepted = heuristic_score >= (ACCEPT_THRESHOLD + REJECT_THRESHOLD) // 2
        return GateResult(
            accepted,
            f"Ambiguous heuristic score ({heuristic_score}); LLM confirmation is not wired up "
            "yet, so this fell back to a heuristic-only decision.",
        )


def _parse_llm_response(raw_response: str) -> GateResult:
    try:
        data = json.loads(raw_response)
        return GateResult(
            bool(data.get("is_contract")),
            data.get("reason", "LLM gate confirmation."),
            data.get("likely_contract_type"),
        )
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Could not parse LLM gate response, rejecting conservatively: %r", raw_response)
        return GateResult(False, "Could not parse LLM gate response; rejected conservatively.")
