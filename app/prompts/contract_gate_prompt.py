"""Prompt for the LLM-confirmation tier of the contract gate. Only used when
the heuristic pre-filter score is ambiguous, and only ever on a short
excerpt — never the full document (see contract_gate_service.py)."""


def build_gate_prompt(excerpt: str) -> str:
    return (
        "You are reviewing a short excerpt from an uploaded document to decide whether it "
        "is a legal contract (e.g. NDA, employment agreement, service agreement, lease, "
        "license, purchase agreement, partnership agreement, etc.).\n\n"
        "Respond with strict JSON only, no other text, in exactly this shape:\n"
        '{"is_contract": true|false, "confidence": 0.0-1.0, '
        '"likely_contract_type": string|null, "reason": string}\n\n'
        f"Excerpt:\n{excerpt}"
    )
