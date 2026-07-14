from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.clause import ClauseAnalysisRead
from app.schemas.document import DocumentRead
from app.schemas.qa import CitationOut


class PartyOut(BaseModel):
    name: str
    role: str | None = None


class ObligationOut(BaseModel):
    party: str
    obligation: str


class ContractSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_type: str
    parties: list[PartyOut]
    effective_date: str | None
    expiration_date: str | None
    key_obligations: list[ObligationOut]
    citations: list[CitationOut]
    risk_summary_narrative: str | None
    risk_counts: dict[str, int]
    created_at: datetime
    updated_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def _default_citations_to_empty_list(cls, value):
        # Rows persisted before Sprint 7.1 (or the SQLite ALTER TABLE
        # backfill) may have NULL here -- treat as "no citations", not a
        # validation error.
        return value or []


class FullReportRead(BaseModel):
    document: DocumentRead
    summary: ContractSummaryRead | None
    clauses: list[ClauseAnalysisRead]
