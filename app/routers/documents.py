from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.document import DocumentListItem, DocumentRead, DocumentUploadResponse
from app.services import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = await file.read()
    document = document_service.upload_document(db, filename=file.filename, contents=contents)
    return document


@router.get("", response_model=list[DocumentListItem])
def list_documents(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return document_service.list_documents(db, offset=offset, limit=limit)


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: int,
    include_text: bool = Query(False, description="Include the full extracted text in the response."),
    db: Session = Depends(get_db),
):
    document = document_service.get_document(db, document_id)
    data = DocumentRead.model_validate(document)
    if not include_text:
        data.raw_text = None
    return data
