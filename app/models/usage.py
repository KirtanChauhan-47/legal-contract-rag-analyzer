from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TokenUsageLog(Base):
    """Append-only log of LLM token usage, one row per LLM call. Powers
    GET /documents/{id}/status's token-cost breakdown. Unlike ClauseAnalysis/
    ContractSummary, rows are never replaced on re-run -- tokens already
    spent stay counted even if the document is later reprocessed, so a
    document's full cost history can be reconstructed and summed by
    action."""

    __tablename__ = "token_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)

    action: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
