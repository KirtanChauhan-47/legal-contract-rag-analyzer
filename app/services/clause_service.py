"""Detects and analyzes each clause type in the fixed taxonomy for a
document. Retrieval-first: for each clause type, one or more targeted
search-query aliases retrieve candidate chunks via the existing hybrid
retrieval_service; if the best candidate doesn't clear
retrieval_service.is_relevant(), the clause is stored as present=false
without ever calling the LLM -- this is what keeps clause analysis from
being 20 unconditional LLM calls per document.

Reuses the same retrieve -> prompt -> LLM -> parse -> verify-citations
pattern qa_service established in Sprint 5, via the shared
citation_verification helpers.
"""
import logging

from sqlalchemy.orm import Session

from app.core.clause_taxonomy import CLAUSE_INFO, CLAUSE_SEARCH_QUERIES, VALID_RISK_LEVELS, ClauseType, RiskLevel
from app.core.exceptions import ConflictError
from app.db.analysis_repository import ClauseAnalysisRepository
from app.models.analysis import ClauseAnalysis
from app.models.document import DocumentStatus
from app.prompts.clause_detection_prompt import SYSTEM_PROMPT, build_clause_prompt
from app.services import document_service, retrieval_service
from app.services.citation_verification import parse_llm_json, verify_citations
from app.services.llm_service import get_llm_provider

logger = logging.getLogger(__name__)

# Candidates retrieved per search-query alias, before dedup/merge across
# a clause type's aliases.
CHUNKS_PER_ALIAS = 3
# Cap on how many merged candidate chunks go into a single clause's prompt.
MAX_CHUNKS_FOR_PROMPT = 6


def analyze_clauses(db: Session, document_id: int) -> list[ClauseAnalysis]:
    """Runs detection for every clause type in the taxonomy and persists
    the results. Safe to call again on an already-analyzed document --
    prior results are replaced, not accumulated."""
    document = document_service.get_document(db, document_id)
    if document.status not in (DocumentStatus.EMBEDDED.value, DocumentStatus.ANALYZED.value):
        raise ConflictError(
            f"Document {document_id} must be embedded before clause analysis "
            f"(current status: '{document.status}')."
        )

    analyses = [_analyze_one_clause(db, document_id, clause_type) for clause_type in ClauseType]

    repo = ClauseAnalysisRepository(db)
    repo.replace_for_document(document_id, analyses)
    document.status = DocumentStatus.ANALYZED.value
    db.commit()

    return repo.list_by_document(document_id)


def get_clauses(db: Session, document_id: int) -> list[ClauseAnalysis]:
    document_service.get_document(db, document_id)  # raises NotFoundError if missing
    return ClauseAnalysisRepository(db).list_by_document(document_id)


def _analyze_one_clause(db: Session, document_id: int, clause_type: ClauseType) -> dict:
    info = CLAUSE_INFO[clause_type]
    aliases = CLAUSE_SEARCH_QUERIES[clause_type]

    # Query every alias and merge by chunk_id, keeping each chunk's best
    # combined_score across aliases -- a clause is only judged absent after
    # ALL of its aliases come up empty/irrelevant, not just one narrow query.
    candidates_by_chunk_id: dict[int, dict] = {}
    for alias in aliases:
        for chunk in retrieval_service.retrieve(db, document_id, alias, top_k=CHUNKS_PER_ALIAS):
            existing = candidates_by_chunk_id.get(chunk["chunk_id"])
            if existing is None or chunk["combined_score"] > existing["combined_score"]:
                candidates_by_chunk_id[chunk["chunk_id"]] = chunk

    candidates = sorted(candidates_by_chunk_id.values(), key=lambda c: c["combined_score"], reverse=True)

    if not candidates or not retrieval_service.is_relevant(candidates[0]):
        return _absent_result(clause_type)

    prompt_chunks = candidates[:MAX_CHUNKS_FOR_PROMPT]
    prompt = build_clause_prompt(info["label"], info["description"], prompt_chunks)

    provider = get_llm_provider()
    raw_response = provider.generate(prompt, system=SYSTEM_PROMPT)

    return _parse_clause_response(raw_response, prompt_chunks, clause_type)


def _absent_result(clause_type: ClauseType) -> dict:
    return {
        "clause_type": clause_type.value,
        "present": False,
        "summary": None,
        "risk_level": RiskLevel.UNKNOWN.value,
        "risk_explanation": None,
        "citations": [],
    }


def _parse_clause_response(raw_response: str, chunks: list[dict], clause_type: ClauseType) -> dict:
    chunk_text_by_id = {chunk["chunk_id"]: chunk["text"] for chunk in chunks}

    data = parse_llm_json(raw_response, required_keys={"present": bool, "citations": list})
    if data is None:
        logger.warning("Could not parse clause analysis response for %s; storing as absent.", clause_type.value)
        return _absent_result(clause_type)

    if not data["present"]:
        return _absent_result(clause_type)

    verified_citations = verify_citations(data["citations"], chunk_text_by_id)
    if not verified_citations:
        # The model claimed this clause is present but none of its
        # citations verify against the retrieved text -- an unsupported
        # "present" claim is never stored as a grounded finding.
        logger.info(
            "Clause %s claimed present but no citations verified; storing as absent instead.",
            clause_type.value,
        )
        return _absent_result(clause_type)

    summary = data.get("summary")
    if not isinstance(summary, str):
        summary = None

    risk_level = data.get("risk_level")
    if risk_level not in VALID_RISK_LEVELS:
        risk_level = RiskLevel.UNKNOWN.value

    risk_explanation = data.get("risk_explanation")
    if not isinstance(risk_explanation, str):
        risk_explanation = None

    return {
        "clause_type": clause_type.value,
        "present": True,
        "summary": summary,
        "risk_level": risk_level,
        "risk_explanation": risk_explanation,
        "citations": verified_citations,
    }
