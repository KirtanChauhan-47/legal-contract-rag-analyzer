from pydantic import BaseModel


class PipelineStatus(BaseModel):
    extracted: bool
    gate_checked: bool
    is_legal_contract: bool | None
    rejection_reason: str | None
    chunked: bool
    chunk_count: int
    embedded: bool
    clauses_analyzed: bool
    clauses_analyzed_count: int
    summarized: bool


class ActionTokenUsage(BaseModel):
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class TokenUsageSummary(BaseModel):
    total_llm_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    by_action: dict[str, ActionTokenUsage]


class DocumentStatusRead(BaseModel):
    document_id: int
    current_status: str
    pipeline: PipelineStatus
    token_usage: TokenUsageSummary
