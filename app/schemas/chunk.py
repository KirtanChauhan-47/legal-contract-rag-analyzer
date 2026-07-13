from pydantic import BaseModel, ConfigDict


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    section_label: str | None
    token_count: int | None


class ChunkSearchResult(BaseModel):
    chunk_id: int
    chunk_index: int
    section_label: str | None
    text: str
    vector_distance: float | None
    keyword_score: float
    exact_phrase_match: bool
    combined_score: float
    match_reason: str
