from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClauseAnalysis(Base):
    __tablename__ = "clause_analyses"
    __table_args__ = (
        # Defense-in-depth alongside ClauseAnalysisRepository.replace_for_document's
        # delete-then-insert strategy: the DB itself refuses a second row for the
        # same document_id + clause_type even if some future code path bypasses
        # the repository.
        UniqueConstraint("document_id", "clause_type", name="uq_clause_analyses_document_clause_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)

    clause_type: Mapped[str] = mapped_column(String(50))
    present: Mapped[bool] = mapped_column(Boolean)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(10), default="unknown")
    risk_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClauseAnalysisRun(Base):
    """Tracks the fingerprint of the inputs (chunk text, taxonomy, prompt,
    model config) behind a document's most recent successful clause
    analysis, so a repeated POST /analyze-clauses can skip re-calling the
    LLM entirely when nothing relevant has changed. One row per document
    (document_id is the primary key) -- no history needed, just current
    state."""

    __tablename__ = "clause_analysis_runs"

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ContractSummary(Base):
    """One row per document (document_id is unique) -- contract-level
    classification, parties/dates/obligations, and a risk rollup. Risk
    counts are computed in code from ClauseAnalysis.risk_level, not
    re-asked of the LLM; only risk_summary_narrative is LLM-generated."""

    __tablename__ = "contract_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), unique=True, index=True)

    contract_type: Mapped[str] = mapped_column(String(30))
    parties: Mapped[list | None] = mapped_column(JSON, nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expiration_date: Mapped[str | None] = mapped_column(String(100), nullable=True)
    key_obligations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    risk_summary_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_counts: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
