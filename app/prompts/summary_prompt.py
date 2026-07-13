"""Prompts for Sprint 7 contract-level summary. Two separate, cheap LLM
calls, both built only from a small curated chunk set (or, for the
narrative, from already-computed risk counts) -- never the full document:

1. Contract type classification + parties/dates/obligations extraction,
   from a curated set of preamble + parties/effective-date-tagged chunks.
2. A short risk narrative, generated from a risk-level breakdown that is
   computed in code (not re-asked of the LLM) plus any high-risk clause
   explanations already on file.
"""
import json

EXTRACTION_SYSTEM_PROMPT = (
    "You are a contract analysis assistant. You are given excerpts from a single legal "
    "contract's opening/preamble section and any sections identifying the parties or "
    "effective date. Classify the contract type, identify the parties, and extract the "
    "effective date, expiration date, and each party's key obligations if evident from "
    "these excerpts.\n\n"
    "This is NOT legal advice -- a plain-language summary only.\n\n"
    "Respond with strict JSON only, no other text, in exactly this shape:\n"
    '{"contract_type": "nda"|"employment"|"service"|"consulting"|"vendor"|"lease"|'
    '"licensing"|"partnership"|"purchase"|"general_business", '
    '"parties": [{"name": string, "role": string|null}], '
    '"effective_date": string|null, "expiration_date": string|null, '
    '"key_obligations": [{"party": string, "obligation": string}], '
    '"citations": [{"chunk_id": int, "quote": string}]}\n\n'
    "If a field cannot be determined from the excerpts, use null or an empty list rather "
    'than guessing -- do not invent parties or dates. If nothing suggests a more specific '
    'type, use "general_business". Each citation\'s quote must be copied verbatim from the '
    "excerpt it references, and should support the parties/dates/obligations you extracted."
)


def build_extraction_prompt(chunks: list[dict]) -> str:
    excerpt_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        label = chunk.get("section_label") or "(no heading)"
        excerpt_blocks.append(f'[Excerpt {i} | Section: "{label}" | chunk_id: {chunk["chunk_id"]}]\n{chunk["text"]}')
    excerpts = "\n\n".join(excerpt_blocks)
    return f"Excerpts:\n{excerpts}"


NARRATIVE_SYSTEM_PROMPT = (
    "You are a contract analysis assistant. You are given a risk-level breakdown for a "
    "contract's clauses that has already been computed -- do not recompute or second-guess "
    "the counts. Write a brief (2-4 sentence) plain-language narrative summarizing the "
    "overall risk picture for a business reviewer, referencing the high-risk clauses given "
    "if any.\n\n"
    "This is NOT legal advice -- a heuristic review aid only. Do not invent clause types, "
    "risk levels, or explanations beyond what is given to you.\n\n"
    'Respond with strict JSON only, no other text: {"narrative": string}'
)


def build_narrative_prompt(risk_counts: dict, high_risk_clauses: list[dict]) -> str:
    return (
        f"Risk-level breakdown (already computed, counts of clauses found present at each "
        f"level): {json.dumps(risk_counts, sort_keys=True)}\n\n"
        f"High-risk clauses and their explanations: {json.dumps(high_risk_clauses, sort_keys=True)}"
    )
