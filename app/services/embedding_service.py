"""Wraps the local sentence-transformers embedding model. Loaded once as a
module-level singleton (lazy — first call pays the load cost, later calls
reuse it) since reloading a transformer model per request would be a real
latency hit.
"""
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None

MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-encodes a list of texts. Used for both chunk text (many at once)
    and a single query string (a list of length 1)."""
    model = _get_model()
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False)
    return embeddings.tolist()
