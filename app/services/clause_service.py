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

Sprint 6.1 cost-reduction pass (see CLAUDE.md): fewer, deduplicated chunks
per prompt, plus a content-fingerprint cache so re-running analysis on an
unchanged document skips the LLM entirely.
"""
import hashlib
import logging

from sqlalchemy.orm import Session

from app.core.clause_taxonomy import CLAUSE_INFO, CLAUSE_SEARCH_QUERIES, VALID_RISK_LEVELS, ClauseType, RiskLevel
from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.db.analysis_repository import ClauseAnalysisRepository, ClauseAnalysisRunRepository
from app.db.chunk_repository import ChunkRepository
from app.models.analysis import ClauseAnalysis
from app.models.document import DocumentStatus
from app.prompts.clause_detection_prompt import SYSTEM_PROMPT, build_clause_prompt
from app.services import document_service, embedding_service, retrieval_service
from app.services.citation_verification import parse_llm_json, verify_citations
from app.services.llm_service import get_llm_provider

logger = logging.getLogger(__name__)

# Candidates retrieved per search-query alias, before dedup/merge across
# a clause type's aliases.
CHUNKS_PER_ALIAS = 3
# Cap on how many merged candidate chunks go into a single clause's prompt.
# Lowered from 6 to 3 (Sprint 6.1): measurement against a real document
# showed most present clauses only ever cited 1-2 chunks, so the extra
# chunks were mostly pure token cost, not accuracy -- verified unchanged
# present/absent results after this change (see CLAUDE.md).
MAX_CHUNKS_FOR_PROMPT = 3
# A candidate whose text overlaps an already-selected chunk's text at or
# above this token-Jaccard-style ratio is treated as a near-duplicate and
# skipped -- real contracts sometimes repeat the same boilerplate
# paragraph in two sections (observed live: a "Governing Law" sentence
# cited from two separate chunks that were nearly identical text).
NEAR_DUPLICATE_OVERLAP_THRESHOLD = 0.85


def analyze_clauses(db: Session, document_id: int, *, force: bool = False) -> list[ClauseAnalysis]:
    """Runs detection for every clause type in the taxonomy and persists
    the results. Safe to call again on an already-analyzed document --
    prior results are replaced, not accumulated.

    Unless force=True, a repeated call is skipped entirely (no LLM calls)
    if a fingerprint of the document's chunk text, clause taxonomy/prompt,
    and configured models exactly matches the last successful run.
    """
    document = document_service.get_document(db, document_id)
    if document.status not in (DocumentStatus.EMBEDDED.value, DocumentStatus.ANALYZED.value):
        raise ConflictError(
            f"Document {document_id} must be embedded before clause analysis "
            f"(current status: '{document.status}')."
        )

    repo = ClauseAnalysisRepository(db)
    run_repo = ClauseAnalysisRunRepository(db)
    current_fingerprint = _compute_analysis_fingerprint(db, document_id)

    if not force:
        existing_run = run_repo.get_for_document(document_id)
        existing_results = repo.list_by_document(document_id)
        if existing_run is not None and existing_run.fingerprint == current_fingerprint and existing_results:
            logger.info(
                "Clause analysis for document %s is up to date (fingerprint match); skipping LLM calls.",
                document_id,
            )
            return existing_results

    analyses = [_analyze_one_clause(db, document_id, clause_type) for clause_type in ClauseType]

    repo.replace_for_document(document_id, analyses)
    run_repo.upsert(document_id, current_fingerprint, model=get_settings().groq_model)
    document.status = DocumentStatus.ANALYZED.value
    db.commit()

    return repo.list_by_document(document_id)


def _compute_analysis_fingerprint(db: Session, document_id: int) -> str:
    """Hashes everything a clause-analysis result depends on: the actual
    chunk text (captures both document content and chunking/re-chunking
    changes), the clause taxonomy + search aliases, the prompt text, and
    the configured LLM/embedding models. Any change to any of these
    changes the fingerprint and invalidates the cache -- no manually
    maintained version numbers to forget to bump."""
    chunks = ChunkRepository(db).list_by_document(document_id)
    chunk_text_blob = "\x00".join(chunk.text for chunk in chunks)
    taxonomy_blob = repr(sorted(CLAUSE_SEARCH_QUERIES.items()))
    settings = get_settings()

    components = "\x00".join(
        [
            chunk_text_blob,
            taxonomy_blob,
            SYSTEM_PROMPT,
            settings.groq_model,
            embedding_service.MODEL_NAME,
        ]
    )
    return hashlib.sha256(components.encode("utf-8")).hexdigest()


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

    prompt_chunks = _select_prompt_chunks(candidates, MAX_CHUNKS_FOR_PROMPT)
    prompt = build_clause_prompt(info["label"], info["description"], prompt_chunks)

    provider = get_llm_provider()
    raw_response = provider.generate(prompt, system=SYSTEM_PROMPT)

    return _parse_clause_response(raw_response, prompt_chunks, clause_type)


def _select_prompt_chunks(candidates: list[dict], max_chunks: int) -> list[dict]:
    """Picks up to max_chunks candidates, in ranked order, skipping any
    candidate whose text is a near-duplicate of one already selected."""
    selected: list[dict] = []
    for candidate in candidates:
        if len(selected) >= max_chunks:
            break
        if any(_is_near_duplicate(candidate["text"], chosen["text"]) for chosen in selected):
            continue
        selected.append(candidate)
    return selected


def _is_near_duplicate(text_a: str, text_b: str, *, threshold: float = NEAR_DUPLICATE_OVERLAP_THRESHOLD) -> bool:
    tokens_a = set(text_a.lower().split())
    tokens_b = set(text_b.lower().split())
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))
    return overlap >= threshold


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
