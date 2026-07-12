"""Thin wrapper around ChromaDB. Deliberate design choice (see CLAUDE.md):
a single persistent collection ("contract_chunks"), metadata-filtered by
document_id, rather than one Chroma collection per document — simpler to
operate, and keeps cross-document search possible later.

Vector IDs are deterministic (f"doc{document_id}_chunk{chunk_id}") so
re-embedding a document is a clean upsert, not an accumulation of stale
vectors.
"""
import os

import chromadb

from app.core.config import get_settings
from app.models.chunk import Chunk

COLLECTION_NAME = "contract_chunks"

_client: chromadb.ClientAPI | None = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        settings = get_settings()
        os.makedirs(settings.chroma_persist_dir, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        _collection = _client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def _vector_id(document_id: int, chunk_id: int) -> str:
    return f"doc{document_id}_chunk{chunk_id}"


def upsert_chunks(document_id: int, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    if not chunks:
        return
    collection = _get_collection()
    collection.upsert(
        ids=[_vector_id(document_id, chunk.id) for chunk in chunks],
        embeddings=embeddings,
        documents=[chunk.text for chunk in chunks],
        metadatas=[
            {
                "document_id": document_id,
                "chunk_id": chunk.id,
                "section_label": chunk.section_label or "",
            }
            for chunk in chunks
        ],
    )


def delete_vectors_for_document(document_id: int) -> None:
    """Purges a document's vectors before re-embedding or on delete, so no
    orphaned vectors accumulate across re-processing runs."""
    collection = _get_collection()
    collection.delete(where={"document_id": document_id})


def query(document_id: int, query_embedding: list[float], top_k: int) -> list[dict]:
    collection = _get_collection()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"document_id": document_id},
    )

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    return [
        {
            "chunk_id": metadatas[i]["chunk_id"],
            "text": documents[i],
            "section_label": metadatas[i].get("section_label") or None,
            "distance": distances[i],
        }
        for i in range(len(ids))
    ]
