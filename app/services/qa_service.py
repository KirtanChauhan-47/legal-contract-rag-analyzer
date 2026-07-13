"""Orchestrates RAG Q&A: retrieve chunks -> build prompt -> call LLM ->
parse + verify citations -> persist chat history. This establishes the
retrieve-then-generate-then-verify pattern that clause detection and
contract summary (later sprints) reuse.
"""
import json
import logging
import re

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.chat_repository import ChatMessageRepository, ChatSessionRepository
from app.models.chat import ChatMessage
from app.models.document import DocumentStatus
from app.prompts.qa_prompt import SYSTEM_PROMPT, build_qa_prompt
from app.services import document_service, retrieval_service
from app.services.llm_service import get_llm_provider

logger = logging.getLogger(__name__)

TOP_K = 6
# Chroma L2 distance above which a chunk's vector signal alone is treated as
# "not actually relevant". Tuned empirically against all-MiniLM-L6-v2 output
# (correct matches typically land under ~1.0, unrelated chunks above ~1.2).
MAX_DISTANCE_FOR_ANSWER = 1.5
# Fraction of meaningful query tokens that must appear in a chunk for its
# keyword signal alone to count as "relevant" (used when there's no exact
# phrase match and the vector distance alone isn't conclusive).
MIN_KEYWORD_SCORE_FOR_ANSWER = 0.5

NOT_FOUND_ANSWER = "This document does not appear to contain information relevant to that question."
# Returned instead of the model's raw prose whenever none of its citations
# verify against the retrieved chunks -- an unsupported claim about a legal
# document must never be handed back as if it were grounded.
UNGROUNDED_ANSWER = (
    "The model's answer could not be verified against the retrieved contract "
    "text, so it is not being returned as a grounded answer. Please rephrase "
    "the question or review the document directly for this information."
)


def ask(db: Session, document_id: int, question: str, session_uuid: str | None) -> dict:
    document = document_service.get_document(db, document_id)
    if document.status != DocumentStatus.EMBEDDED.value:
        raise ConflictError(
            f"Document {document_id} is not embedded yet (current status: '{document.status}')."
        )

    session_repo = ChatSessionRepository(db)
    if session_uuid:
        # Scoped to document_id -- a session UUID created for a different
        # document must never resolve here, even if the UUID itself exists.
        session = session_repo.get_by_uuid_for_document(session_uuid, document_id)
        if session is None:
            raise ConflictError(f"Chat session '{session_uuid}' not found for document {document_id}.")
    else:
        session = session_repo.create(document_id=document_id)

    message_repo = ChatMessageRepository(db)
    message_repo.create(session_id=session.id, role="user", content=question, citations=None)

    chunks = retrieval_service.retrieve(db, document_id, question, top_k=TOP_K)

    if not chunks or not _is_relevant(chunks[0]):
        answer_text = NOT_FOUND_ANSWER
        verified_citations: list[dict] = []
    else:
        prompt = build_qa_prompt(question, chunks)
        provider = get_llm_provider()
        raw_response = provider.generate(prompt, system=SYSTEM_PROMPT)
        answer_text, verified_citations = _parse_and_verify(raw_response, chunks)
        if not verified_citations:
            logger.info(
                "LLM answer for document %s had zero verified citations; withholding as ungrounded.",
                document_id,
            )
            answer_text = UNGROUNDED_ANSWER

    message_repo.create(session_id=session.id, role="assistant", content=answer_text, citations=verified_citations)

    return {"session_id": session.uuid, "answer": answer_text, "citations": verified_citations}


def _is_relevant(top_chunk: dict) -> bool:
    """Mirrors retrieval_service's hybrid signals: a chunk counts as
    relevant if it exactly contains the query phrase, has strong keyword
    overlap, or is close enough by vector distance -- any one is enough."""
    if top_chunk["exact_phrase_match"]:
        return True
    if top_chunk["keyword_score"] >= MIN_KEYWORD_SCORE_FOR_ANSWER:
        return True
    return top_chunk["vector_distance"] is not None and top_chunk["vector_distance"] <= MAX_DISTANCE_FOR_ANSWER


def _parse_and_verify(raw_response: str, chunks: list[dict]) -> tuple[str, list[dict]]:
    chunk_text_by_id = {chunk["chunk_id"]: chunk["text"] for chunk in chunks}

    data = _parse_llm_json(raw_response)
    if data is None:
        return raw_response, []

    answer = data["answer"]
    raw_citations = data["citations"]

    verified = []
    for citation in raw_citations:
        if not isinstance(citation, dict):
            continue
        chunk_id = citation.get("chunk_id")
        quote = citation.get("quote", "")
        chunk_text = chunk_text_by_id.get(chunk_id)
        if chunk_text and isinstance(quote, str) and _quote_appears_in(quote, chunk_text):
            verified.append({"chunk_id": chunk_id, "quote": quote})
        else:
            logger.info("Dropping unverifiable citation for chunk_id=%s", chunk_id)

    return answer, verified


_MARKDOWN_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """Some models wrap JSON in a ```json ... ``` fence even when told not
    to. Groq's JSON mode shouldn't do this, but parsing defensively costs
    nothing and protects against a future provider swap."""
    stripped = text.strip()
    match = _MARKDOWN_FENCE_PATTERN.match(stripped)
    return match.group(1).strip() if match else stripped


def _parse_llm_json(raw_response: str) -> dict | None:
    """Parses and validates the LLM's structured response. Returns None
    (never a partially-trusted dict) if the text isn't valid JSON or
    doesn't have the expected {"answer": str, "citations": list} shape --
    callers must treat None as "nothing verified", not fall back to
    trusting raw model text."""
    if not isinstance(raw_response, str):
        return None

    try:
        data = json.loads(_strip_markdown_fences(raw_response))
    except json.JSONDecodeError:
        logger.warning("Could not parse LLM QA response as JSON: %r", raw_response)
        return None

    if not isinstance(data, dict) or not isinstance(data.get("answer"), str) or not isinstance(data.get("citations"), list):
        logger.warning("LLM QA response had an unexpected shape: %r", data)
        return None

    return data


def _quote_appears_in(quote: str, chunk_text: str) -> bool:
    normalize = lambda s: " ".join(s.split())
    return bool(quote.strip()) and normalize(quote) in normalize(chunk_text)


def get_chat_history(db: Session, document_id: int) -> list[ChatMessage]:
    document_service.get_document(db, document_id)  # raises NotFoundError if missing
    return ChatMessageRepository(db).list_for_document(document_id)
