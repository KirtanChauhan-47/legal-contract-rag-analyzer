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
    text: str
    section_label: str | None
    distance: float
