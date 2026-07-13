"""Clause-analysis-specific data access, kept out of the generic
Repository per its own docstring: model-specific query logic gets its own
module."""
from sqlalchemy.orm import Session

from app.db.repository import Repository
from app.models.analysis import ClauseAnalysis


class ClauseAnalysisRepository(Repository[ClauseAnalysis]):
    def __init__(self, db: Session):
        super().__init__(db, ClauseAnalysis)

    def list_by_document(self, document_id: int) -> list[ClauseAnalysis]:
        return (
            self.db.query(ClauseAnalysis)
            .filter(ClauseAnalysis.document_id == document_id)
            .order_by(ClauseAnalysis.clause_type)
            .all()
        )

    def replace_for_document(self, document_id: int, analyses: list[dict]) -> None:
        """Deletes existing clause analyses for a document and inserts new
        ones. Does not commit -- caller controls the transaction. Keeps
        re-running analysis idempotent (one row per document_id +
        clause_type) instead of accumulating duplicates."""
        self.db.query(ClauseAnalysis).filter(ClauseAnalysis.document_id == document_id).delete()
        for analysis in analyses:
            self.db.add(ClauseAnalysis(document_id=document_id, **analysis))
