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
