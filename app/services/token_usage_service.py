"""Records per-action LLM token usage so GET /documents/{id}/status can
report cost alongside pipeline progress (see status_service.py). Every LLM
call site (contract gate confirmation, ask, clause analysis, summary
extraction/narrative) calls log_usage() right after provider.generate()
returns.

Providers report usage via the optional LLMProvider.last_usage attribute
(see llm_service.py) rather than a changed generate() return type, so the
many fake/stub providers used throughout the test suite don't need to
change -- they simply have no usage to report, and log_usage() no-ops in
that case rather than logging fabricated zeros.
"""
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.usage_repository import TokenUsageRepository

# Stable action identifiers shared between the LLM call sites (which log
# usage) and status_service (which reports it back) -- one per distinct
# LLM call in the pipeline.
ACTION_CONTRACT_GATE = "contract_gate"
ACTION_QA_ASK = "qa_ask"
ACTION_ANALYZE_CLAUSES = "analyze_clauses"
ACTION_SUMMARIZE_EXTRACTION = "summarize_extraction"
ACTION_SUMMARIZE_NARRATIVE = "summarize_narrative"


def log_usage(db: Session, document_id: int, *, action: str, provider) -> None:
    usage = getattr(provider, "last_usage", None)
    if not usage:
        return
    TokenUsageRepository(db).create(
        document_id=document_id,
        action=action,
        model=get_settings().groq_model,
        prompt_tokens=usage.get("prompt_tokens", 0) or 0,
        completion_tokens=usage.get("completion_tokens", 0) or 0,
        total_tokens=usage.get("total_tokens", 0) or 0,
    )
