"""Prompt for RAG Q&A. The LLM only ever sees retrieved excerpts here, never
the full document — see qa_service.py."""

SYSTEM_PROMPT = (
    "You are a contract analysis assistant. Answer the user's question using ONLY the "
    "excerpts provided below, which come from a single legal contract. Do not use outside "
    "knowledge and do not guess. If the excerpts do not contain enough information to "
    "answer, say so explicitly instead of guessing.\n\n"
    "Respond with strict JSON only, no other text, in exactly this shape:\n"
    '{"answer": string, "citations": [{"chunk_id": int, "quote": string}]}\n\n'
    'Each citation\'s "quote" must be copied verbatim from the excerpt it references.'
)


def build_qa_prompt(question: str, chunks: list[dict]) -> str:
    excerpt_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        label = chunk.get("section_label") or "(no heading)"
        excerpt_blocks.append(
            f'[Excerpt {i} | Section: "{label}" | chunk_id: {chunk["chunk_id"]}]\n{chunk["text"]}'
        )
    excerpts = "\n\n".join(excerpt_blocks)
    return f"Question: {question}\n\nExcerpts:\n{excerpts}"
