"""Token-usage-log data access, kept out of the generic Repository per its
own docstring: model-specific query logic gets its own module."""
from sqlalchemy.orm import Session

from app.db.repository import Repository
from app.models.usage import TokenUsageLog


class TokenUsageRepository(Repository[TokenUsageLog]):
    def __init__(self, db: Session):
        super().__init__(db, TokenUsageLog)

    def list_by_document(self, document_id: int) -> list[TokenUsageLog]:
        return (
            self.db.query(TokenUsageLog)
            .filter(TokenUsageLog.document_id == document_id)
            .order_by(TokenUsageLog.created_at)
            .all()
        )
