from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.clause import ClauseAnalysisRead
from app.schemas.document import DocumentRead


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
    risk_summary_narrative: str | None
    risk_counts: dict[str, int]
    created_at: datetime
    updated_at: datetime


class FullReportRead(BaseModel):
    document: DocumentRead
    summary: ContractSummaryRead | None
    clauses: list[ClauseAnalysisRead]
