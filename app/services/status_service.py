"""Read-only rollup of a document's pipeline progress and cumulative LLM
token cost, for GET /documents/{id}/status. Purely a reporting layer over
already-persisted state (Document.status, chunk/clause/summary rows,
TokenUsageLog) -- it runs no pipeline steps itself and calls no LLM.

_covers_full_taxonomy() is intentionally duplicated from clause_service/
summary_service's identical helper rather than imported, matching this
project's existing convention (see summary_service.py) of not coupling
services together for one small shared check.
"""
from collections import defaultdict

from sqlalchemy.orm import Session

from app.core.clause_taxonomy import ClauseType
from app.db.analysis_repository import ClauseAnalysisRepository, ContractSummaryRepository
from app.db.chunk_repository import ChunkRepository
from app.db.usage_repository import TokenUsageRepository
from app.models.document import DocumentStatus
from app.services import document_service


def get_document_status(db: Session, document_id: int) -> dict:
    document = document_service.get_document(db, document_id)  # raises NotFoundError if missing

    chunks = ChunkRepository(db).list_by_document(document_id)
    clause_rows = ClauseAnalysisRepository(db).list_by_document(document_id)
    summary = ContractSummaryRepository(db).get_for_document(document_id)

    pipeline = {
        "extracted": document.status != DocumentStatus.UPLOADED.value,
        "gate_checked": document.is_legal_contract is not None,
        "is_legal_contract": document.is_legal_contract,
        "rejection_reason": document.rejection_reason,
        "chunked": document.status
        in (DocumentStatus.CHUNKED.value, DocumentStatus.EMBEDDED.value, DocumentStatus.ANALYZED.value),
        "chunk_count": len(chunks),
        "embedded": document.status in (DocumentStatus.EMBEDDED.value, DocumentStatus.ANALYZED.value),
        "clauses_analyzed": _covers_full_taxonomy(clause_rows),
        "clauses_analyzed_count": len(clause_rows),
        "summarized": summary is not None,
    }

    usage_rows = TokenUsageRepository(db).list_by_document(document_id)
    by_action: dict[str, dict] = defaultdict(lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    for row in usage_rows:
        bucket = by_action[row.action]
        bucket["calls"] += 1
        bucket["prompt_tokens"] += row.prompt_tokens
        bucket["completion_tokens"] += row.completion_tokens
        bucket["total_tokens"] += row.total_tokens

    token_usage = {
        "total_llm_calls": len(usage_rows),
        "total_prompt_tokens": sum(row.prompt_tokens for row in usage_rows),
        "total_completion_tokens": sum(row.completion_tokens for row in usage_rows),
        "total_tokens": sum(row.total_tokens for row in usage_rows),
        "by_action": dict(by_action),
    }

    return {
        "document_id": document.id,
        "current_status": document.status,
        "pipeline": pipeline,
        "token_usage": token_usage,
    }


def _covers_full_taxonomy(clause_rows) -> bool:
    if len(clause_rows) != len(ClauseType):
        return False
    return {row.clause_type for row in clause_rows} == {clause_type.value for clause_type in ClauseType}
