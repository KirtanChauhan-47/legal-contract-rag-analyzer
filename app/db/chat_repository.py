"""Chat-specific data access, kept out of the generic Repository per its
own docstring: model-specific query logic gets its own module."""
from sqlalchemy.orm import Session

from app.db.repository import Repository
from app.models.chat import ChatMessage, ChatSession


class ChatSessionRepository(Repository[ChatSession]):
    def __init__(self, db: Session):
        super().__init__(db, ChatSession)

    def get_by_uuid(self, session_uuid: str) -> ChatSession | None:
        return self.db.query(ChatSession).filter(ChatSession.uuid == session_uuid).first()


class ChatMessageRepository(Repository[ChatMessage]):
    def __init__(self, db: Session):
        super().__init__(db, ChatMessage)

    def list_for_document(self, document_id: int) -> list[ChatMessage]:
        return (
            self.db.query(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .filter(ChatSession.document_id == document_id)
            .order_by(ChatMessage.created_at)
            .all()
        )
