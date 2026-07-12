"""Chunk-specific data access, kept out of the generic Repository per its
own docstring: model-specific query logic gets its own module."""
from sqlalchemy.orm import Session

from app.db.repository import Repository
from app.models.chunk import Chunk


class ChunkRepository(Repository[Chunk]):
    def __init__(self, db: Session):
        super().__init__(db, Chunk)

    def list_by_document(self, document_id: int) -> list[Chunk]:
        return (
            self.db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
            .all()
        )

    def replace_for_document(self, document_id: int, chunk_dicts: list[dict]) -> None:
        """Deletes existing chunks for a document and inserts new ones.
        Does not commit — caller controls the transaction. Keeps
        re-processing idempotent instead of accumulating duplicate chunks."""
        self.db.query(Chunk).filter(Chunk.document_id == document_id).delete()
        for chunk_dict in chunk_dicts:
            self.db.add(Chunk(document_id=document_id, **chunk_dict))
