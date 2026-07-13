"""Retrieves the top-k most relevant chunks for a query, scoped to one
document. The single place both the Sprint 4 search debug endpoint and
Sprint 5's RAG Q&A go through for retrieval."""
from app.services import embedding_service, vector_store_service


def retrieve(document_id: int, query_text: str, *, top_k: int = 5) -> list[dict]:
    query_embedding = embedding_service.embed_texts([query_text])[0]
    return vector_store_service.query(document_id, query_embedding, top_k)
