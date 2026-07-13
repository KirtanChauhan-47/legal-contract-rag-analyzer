from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.qa import AskRequest, AskResponse, ChatMessageRead
from app.services import qa_service

router = APIRouter(prefix="/documents", tags=["qa"])


@router.post("/{document_id}/ask", response_model=AskResponse)
def ask_question(document_id: int, body: AskRequest, db: Session = Depends(get_db)):
    return qa_service.ask(db, document_id, body.question, body.session_id)


@router.get("/{document_id}/chat", response_model=list[ChatMessageRead])
def get_chat(document_id: int, db: Session = Depends(get_db)):
    return qa_service.get_chat_history(db, document_id)
