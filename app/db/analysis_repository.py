"""Clause-analysis-specific data access, kept out of the generic
Repository per its own docstring: model-specific query logic gets its own
module."""
from sqlalchemy.orm import Session

from app.db.repository import Repository
from app.models.analysis import ClauseAnalysis, ClauseAnalysisRun, ContractSummary


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


class ClauseAnalysisRunRepository(Repository[ClauseAnalysisRun]):
    def __init__(self, db: Session):
        super().__init__(db, ClauseAnalysisRun)

    def get_for_document(self, document_id: int) -> ClauseAnalysisRun | None:
        return self.db.get(ClauseAnalysisRun, document_id)

    def upsert(self, document_id: int, fingerprint: str, *, model: str) -> None:
        """Records (or updates) the fingerprint of the inputs used for a
        document's most recent successful clause analysis run. Does not
        commit -- caller controls the transaction."""
        existing = self.get_for_document(document_id)
        if existing is None:
            self.db.add(ClauseAnalysisRun(document_id=document_id, fingerprint=fingerprint, model=model))
        else:
            existing.fingerprint = fingerprint
            existing.model = model


class ContractSummaryRepository(Repository[ContractSummary]):
    def __init__(self, db: Session):
        super().__init__(db, ContractSummary)

    def get_for_document(self, document_id: int) -> ContractSummary | None:
        return self.db.query(ContractSummary).filter(ContractSummary.document_id == document_id).first()

    def upsert(self, document_id: int, fields: dict) -> ContractSummary:
        """Updates the existing summary in place, or creates one -- a
        document has at most one summary (unique document_id), so this is
        naturally idempotent without a delete-then-insert step. Does not
        commit -- caller controls the transaction."""
        existing = self.get_for_document(document_id)
        if existing is None:
            summary = ContractSummary(document_id=document_id, **fields)
            self.db.add(summary)
            return summary
        for key, value in fields.items():
            setattr(existing, key, value)
        return existing
