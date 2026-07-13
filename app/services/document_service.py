"""Orchestrates document upload: validate -> save to disk -> extract text ->
persist. Kept separate from extraction_service so the router stays a thin
pass-through and all DB/file-system side effects live in one place."""
import os
import uuid as uuid_lib

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.db.chunk_repository import ChunkRepository
from app.db.repository import Repository
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services import chunking_service, cleaning_service, contract_gate_service
from app.services import embedding_service, retrieval_service, vector_store_service
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


def process_document(db: Session, document_id: int) -> Document:
    """Runs gate -> clean -> chunk. Safe to call again on an already-processed
    document (e.g. to retry after tuning) — prior chunks are replaced, not
    accumulated."""
    document = get_document(db, document_id)

    if document.status == DocumentStatus.UPLOADED.value:
        raise ConflictError(f"Document {document_id} has not finished text extraction yet.")
    if document.status == DocumentStatus.FAILED.value:
        raise ConflictError(f"Document {document_id} failed extraction: {document.error_message}")

    gate_result = contract_gate_service.run_gate(document.raw_text)
    document.is_legal_contract = gate_result.is_contract
    document.rejection_reason = None if gate_result.is_contract else gate_result.reason
    if gate_result.contract_type:
        document.contract_type = gate_result.contract_type

    chunk_repo = ChunkRepository(db)

    # Replacing chunks invalidates any previously embedded vectors for this
    # document (old chunk_ids no longer exist) — purge them so re-processing
    # never leaves orphaned vectors behind (guardrail: vectors + SQL rows
    # stay in sync).
    vector_store_service.delete_vectors_for_document(document.id)

    if not gate_result.is_contract:
        document.status = DocumentStatus.GATED_REJECTED.value
        chunk_repo.replace_for_document(document.id, [])
        db.commit()
        db.refresh(document)
        return document

    document.cleaned_text = cleaning_service.clean_text(document.raw_text)
    chunk_dicts = chunking_service.chunk_document(document.cleaned_text)
    chunk_repo.replace_for_document(document.id, chunk_dicts)

    document.status = DocumentStatus.CHUNKED.value
    db.commit()
    db.refresh(document)
    return document


def get_chunks(db: Session, document_id: int) -> list[Chunk]:
    get_document(db, document_id)  # raises NotFoundError if missing
    return ChunkRepository(db).list_by_document(document_id)


def embed_document(db: Session, document_id: int) -> Document:
    """Embeds all of a document's chunks and upserts them into the vector
    store. Safe to call again (e.g. after re-processing) — old vectors for
    the document are purged first, never accumulated."""
    document = get_document(db, document_id)

    if document.status not in (DocumentStatus.CHUNKED.value, DocumentStatus.EMBEDDED.value):
        raise ConflictError(
            f"Document {document_id} must be chunked before embedding (current status: '{document.status}')."
        )

    chunk_repo = ChunkRepository(db)
    chunks = chunk_repo.list_by_document(document_id)
    if not chunks:
        raise ConflictError(f"Document {document_id} has no chunks to embed.")

    embeddings = embedding_service.embed_texts([chunk.text for chunk in chunks])

    vector_store_service.delete_vectors_for_document(document_id)
    vector_store_service.upsert_chunks(document_id, chunks, embeddings)

    for chunk in chunks:
        chunk.embedding_id = f"doc{document_id}_chunk{chunk.id}"

    document.status = DocumentStatus.EMBEDDED.value
    db.commit()
    db.refresh(document)
    return document


def search_document(db: Session, document_id: int, query_text: str, *, top_k: int = 5) -> list[dict]:
    document = get_document(db, document_id)

    if document.status != DocumentStatus.EMBEDDED.value:
        raise ConflictError(
            f"Document {document_id} is not embedded yet (current status: '{document.status}')."
        )

    return retrieval_service.retrieve(document_id, query_text, top_k=top_k)
