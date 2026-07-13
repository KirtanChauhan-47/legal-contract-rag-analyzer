from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.chunk import ChunkRead, ChunkSearchResult
from app.schemas.clause import ClauseAnalysisRead
from app.schemas.document import DocumentListItem, DocumentRead, DocumentUploadResponse
from app.services import clause_service, document_service

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


@router.post("/{document_id}/process", response_model=DocumentRead)
def process_document(document_id: int, db: Session = Depends(get_db)):
    document = document_service.process_document(db, document_id)
    data = DocumentRead.model_validate(document)
    data.raw_text = None
    return data


@router.get("/{document_id}/chunks", response_model=list[ChunkRead])
def get_chunks(document_id: int, db: Session = Depends(get_db)):
    return document_service.get_chunks(db, document_id)


@router.post("/{document_id}/embed", response_model=DocumentRead)
def embed_document(document_id: int, db: Session = Depends(get_db)):
    document = document_service.embed_document(db, document_id)
    data = DocumentRead.model_validate(document)
    data.raw_text = None
    return data


@router.get("/{document_id}/search", response_model=list[ChunkSearchResult])
def search_document(
    document_id: int,
    q: str = Query(..., min_length=1, description="Query text to semantically search for."),
    top_k: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return document_service.search_document(db, document_id, q, top_k=top_k)


@router.post("/{document_id}/analyze-clauses", response_model=list[ClauseAnalysisRead])
def analyze_clauses(
    document_id: int,
    force: bool = Query(False, description="Re-run and call the LLM even if cached results are still valid."),
    db: Session = Depends(get_db),
):
    return clause_service.analyze_clauses(db, document_id, force=force)


@router.get("/{document_id}/clauses", response_model=list[ClauseAnalysisRead])
def get_clauses(document_id: int, db: Session = Depends(get_db)):
    return clause_service.get_clauses(db, document_id)
