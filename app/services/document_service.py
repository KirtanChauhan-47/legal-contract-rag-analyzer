"""Orchestrates document upload: validate -> save to disk -> extract text ->
persist. Kept separate from extraction_service so the router stays a thin
pass-through and all DB/file-system side effects live in one place."""
import os
import uuid as uuid_lib

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.db.repository import Repository
from app.models.document import Document, DocumentStatus
from app.services.extraction_service import ExtractionError, extract_text
from app.utils.file_validation import validate_upload


def upload_document(db: Session, *, filename: str, contents: bytes) -> Document:
    settings = get_settings()
    validate_upload(filename, contents)

    file_ext = os.path.splitext(filename)[1].lower().lstrip(".")
    file_uuid = str(uuid_lib.uuid4())

    os.makedirs(settings.upload_dir, exist_ok=True)
    stored_path = os.path.join(settings.upload_dir, f"{file_uuid}_{filename}")
    with open(stored_path, "wb") as f:
        f.write(contents)

    repo = Repository(db, Document)
    document = repo.create(
        uuid=file_uuid,
        original_filename=filename,
        stored_path=stored_path,
        file_type=file_ext,
        file_size_bytes=len(contents),
        status=DocumentStatus.UPLOADED.value,
    )

    try:
        text, page_count = extract_text(stored_path, file_ext)
        document.raw_text = text
        document.page_count = page_count
        document.status = DocumentStatus.EXTRACTED.value
    except ExtractionError as exc:
        document.status = DocumentStatus.FAILED.value
        document.error_message = str(exc)

    db.commit()
    db.refresh(document)
    return document


def get_document(db: Session, document_id: int) -> Document:
    repo = Repository(db, Document)
    document = repo.get(document_id)
    if document is None:
        raise NotFoundError(f"Document {document_id} not found.")
    return document


def list_documents(db: Session, *, offset: int = 0, limit: int = 20) -> list[Document]:
    repo = Repository(db, Document)
    return repo.list(offset=offset, limit=limit)
