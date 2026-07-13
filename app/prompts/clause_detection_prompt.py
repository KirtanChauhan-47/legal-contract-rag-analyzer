"""Prompt for per-clause-type structured analysis. Built only from chunks
already retrieved for that clause type -- never the full document. See
clause_service.py for the retrieval-first gating that decides whether this
prompt is even built for a given clause type."""

# Bumped whenever SYSTEM_PROMPT or build_clause_prompt's shape changes in a
# way that could change model output -- folded into clause_service's cache
# fingerprint as an explicit, human-reviewable marker alongside the raw
# prompt text itself (which already invalidates the cache automatically on
# any edit; this constant documents *that* a deliberate revision happened).
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = (
    "You are a contract analysis assistant helping a user understand a legal contract. "
    "You are given excerpts from a single contract that were retrieved because they are "
    "likely relevant to one specific clause type. Determine whether this clause type is "
    "actually present in the excerpts, and if so, summarize it and rate its risk level.\n\n"
    "IMPORTANT: This is NOT legal advice. risk_level is a heuristic review signal meant to "
    "help a human reviewer prioritize what to look at closely -- it is not a legal risk "
    "assessment and must not be presented with false certainty.\n\n"
    "Respond with strict JSON only, no other text, in exactly this shape:\n"
    '{"present": true|false, "summary": string|null, "risk_level": "low"|"medium"|"high"|"unknown", '
    '"risk_explanation": string|null, "citations": [{"chunk_id": int, "quote": string}]}\n\n'
    'If the excerpts do not actually contain this clause type, set present to false, summary '
    'and risk_explanation to null, risk_level to "unknown", and citations to an empty list -- '
    'do not guess or force a match just because excerpts were provided. Each citation\'s '
    '"quote" must be copied verbatim from the excerpt it references.'
)


def build_clause_prompt(clause_label: str, clause_description: str, chunks: list[dict]) -> str:
    excerpt_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        label = chunk.get("section_label") or "(no heading)"
        excerpt_blocks.append(
            f'[Excerpt {i} | Section: "{label}" | chunk_id: {chunk["chunk_id"]}]\n{chunk["text"]}'
        )
    excerpts = "\n\n".join(excerpt_blocks)
    return f'Clause type to look for: "{clause_label}" ({clause_description})\n\nExcerpts:\n{excerpts}'
