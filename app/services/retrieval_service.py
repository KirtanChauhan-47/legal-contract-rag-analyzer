"""Retrieves the top-k most relevant chunks for a query, scoped to one
document. The single place both the search debug endpoint and RAG Q&A go
through for retrieval.

Hybrid by design: pure vector similarity under-ranks (or entirely misses,
if a match falls outside the vector candidate pool) chunks containing an
exact legal defined term the user searched for verbatim — e.g. a query for
"Allowable Deductions" should find the chunk containing that exact phrase
regardless of how Chroma's embedding distance happens to rank it. So every
chunk in the document is also scored for exact-phrase and keyword overlap
against the raw SQL chunk text (the authoritative source), and the two
signals are combined into one ranking.
"""
import re

from sqlalchemy.orm import Session

from app.db.chunk_repository import ChunkRepository
from app.services import embedding_service, vector_store_service

# How many nearest-by-vector chunks to pull from Chroma as candidates,
# before hybrid scoring narrows down to top_k. Wider than top_k so a chunk
# that's semantically "close enough" but not literally translated by the
# tokenizer still gets a chance to be re-ranked in via keyword/phrase score.
VECTOR_CANDIDATE_POOL = 20

# Chroma L2 distance is unbounded-ish; this caps it before converting to a
# 0..1 "similarity" so it combines sensibly with the other signals.
MAX_EXPECTED_DISTANCE = 2.0

EXACT_PHRASE_BONUS = 5.0
KEYWORD_WEIGHT = 1.0
VECTOR_WEIGHT = 1.0

# Thresholds for is_relevant() below -- shared by qa_service (per user
# question) and clause_service (per clause-type search) to decide whether
# retrieved evidence is strong enough to bother calling the LLM at all.
# Chroma L2 distance above which a chunk's vector signal alone is treated
# as "not actually relevant". Tuned empirically against all-MiniLM-L6-v2
# output (correct matches typically land under ~1.0, unrelated above ~1.2).
MAX_DISTANCE_FOR_RELEVANCE = 1.5
# Fraction of meaningful query tokens that must appear in a chunk for its
# keyword signal alone to count as "relevant" (used when there's no exact
# phrase match and the vector distance alone isn't conclusive).
MIN_KEYWORD_SCORE_FOR_RELEVANCE = 0.5

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "and", "or",
    "what", "which", "that", "this", "these", "those", "for", "on", "by", "with",
    "as", "be", "shall", "does", "do", "did", "from", "at", "it", "its",
}


def retrieve(db: Session, document_id: int, query_text: str, *, top_k: int = 5) -> list[dict]:
    query_embedding = embedding_service.embed_texts([query_text])[0]
    vector_hits = vector_store_service.query(document_id, query_embedding, VECTOR_CANDIDATE_POOL)
    vector_distance_by_chunk_id = {hit["chunk_id"]: hit["distance"] for hit in vector_hits}

    chunks = ChunkRepository(db).list_by_document(document_id)
    query_tokens = _tokenize(query_text)
    normalized_query = _normalize(query_text)

    candidates = []
    for chunk in chunks:
        distance = vector_distance_by_chunk_id.get(chunk.id)
        exact_phrase_match = bool(normalized_query) and normalized_query in _normalize(chunk.text)
        keyword_score = _keyword_overlap_score(query_tokens, chunk.text)

        if distance is None and not exact_phrase_match and keyword_score == 0:
            continue  # irrelevant by every signal available — drop it

        vector_similarity = (
            max(0.0, 1 - min(distance, MAX_EXPECTED_DISTANCE) / MAX_EXPECTED_DISTANCE)
            if distance is not None
            else 0.0
        )
        combined_score = (
            (EXACT_PHRASE_BONUS if exact_phrase_match else 0.0)
            + KEYWORD_WEIGHT * keyword_score
            + VECTOR_WEIGHT * vector_similarity
        )

        if exact_phrase_match:
            match_reason = "exact_phrase"
        elif keyword_score > 0 and distance is not None:
            match_reason = "keyword+vector"
        elif keyword_score > 0:
            match_reason = "keyword"
        else:
            match_reason = "vector"

        candidates.append(
            {
                "chunk_id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "section_label": chunk.section_label,
                "text": chunk.text,
                "vector_distance": distance,
                "keyword_score": round(keyword_score, 4),
                "exact_phrase_match": exact_phrase_match,
                "combined_score": round(combined_score, 4),
                "match_reason": match_reason,
            }
        )

    candidates.sort(key=lambda c: c["combined_score"], reverse=True)
    return candidates[:top_k]


def is_relevant(top_chunk: dict) -> bool:
    """Whether a retrieved chunk represents strong enough evidence to act
    on (answer a question from it, or treat a clause type as present) --
    any one signal (exact phrase, keyword overlap, or close vector
    distance) is sufficient. Shared by qa_service and clause_service so
    both retrieve-then-generate pipelines apply the same bar before
    spending an LLM call."""
    if top_chunk["exact_phrase_match"]:
        return True
    if top_chunk["keyword_score"] >= MIN_KEYWORD_SCORE_FOR_RELEVANCE:
        return True
    return top_chunk["vector_distance"] is not None and top_chunk["vector_distance"] <= MAX_DISTANCE_FOR_RELEVANCE


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


def _keyword_overlap_score(query_tokens: list[str], chunk_text: str) -> float:
    if not query_tokens:
        return 0.0
    chunk_tokens = set(re.findall(r"[a-z0-9]+", chunk_text.lower()))
    matched = sum(1 for token in query_tokens if token in chunk_tokens)
    return matched / len(query_tokens)
