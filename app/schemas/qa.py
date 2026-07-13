from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None


class CitationOut(BaseModel):
    chunk_id: int
    quote: str


class AskResponse(BaseModel):
    session_id: str
    answer: str
    citations: list[CitationOut]


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    citations: list[CitationOut] | None
    created_at: datetime
