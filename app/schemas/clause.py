from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.qa import CitationOut


class ClauseAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clause_type: str
    present: bool
    summary: str | None
    risk_level: str
    risk_explanation: str | None
    citations: list[CitationOut] | None
    created_at: datetime
    updated_at: datetime
