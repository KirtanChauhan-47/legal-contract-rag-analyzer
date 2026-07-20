"""Orchestrates RAG Q&A: retrieve chunks -> build prompt -> call LLM ->
parse + verify citations -> persist chat history. This establishes the
retrieve-then-generate-then-verify pattern that clause_service (Sprint 6)
reuses via the shared citation_verification helpers and retrieval_service's
is_relevant() gate.
"""
import logging

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.chat_repository import ChatMessageRepository, ChatSessionRepository
from app.models.chat import ChatMessage
from app.models.document import DocumentStatus
from app.prompts.qa_prompt import SYSTEM_PROMPT, build_qa_prompt
from app.services import document_service, retrieval_service, token_usage_service
from app.services.citation_verification import parse_llm_json, verify_citations
from app.services.llm_service import get_llm_provider

logger = logging.getLogger(__name__)

TOP_K = 6

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

    if not chunks or not retrieval_service.is_relevant(chunks[0]):
        answer_text = NOT_FOUND_ANSWER
        verified_citations: list[dict] = []
    else:
        prompt = build_qa_prompt(question, chunks)
        provider = get_llm_provider()
        raw_response = provider.generate(prompt, system=SYSTEM_PROMPT)
        token_usage_service.log_usage(db, document_id, action=token_usage_service.ACTION_QA_ASK, provider=provider)
        answer_text, verified_citations = _parse_and_verify(raw_response, chunks)
        if not verified_citations:
            logger.info(
                "LLM answer for document %s had zero verified citations; withholding as ungrounded.",
                document_id,
            )
            answer_text = UNGROUNDED_ANSWER

    message_repo.create(session_id=session.id, role="assistant", content=answer_text, citations=verified_citations)

    return {"session_id": session.uuid, "answer": answer_text, "citations": verified_citations}


def _parse_and_verify(raw_response: str, chunks: list[dict]) -> tuple[str, list[dict]]:
    chunk_text_by_id = {chunk["chunk_id"]: chunk["text"] for chunk in chunks}

    data = parse_llm_json(raw_response, required_keys={"answer": str, "citations": list})
    if data is None:
        return raw_response, []

    answer = data["answer"]
    verified = verify_citations(data["citations"], chunk_text_by_id)
    return answer, verified


def get_chat_history(db: Session, document_id: int) -> list[ChatMessage]:
    document_service.get_document(db, document_id)  # raises NotFoundError if missing
    return ChatMessageRepository(db).list_for_document(document_id)
