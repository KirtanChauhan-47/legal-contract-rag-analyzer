from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    original_filename: str
    file_type: str
    status: str
    page_count: int | None
    error_message: str | None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    status: str
    page_count: int | None
    is_legal_contract: bool | None
    rejection_reason: str | None
    contract_type: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    raw_text: str | None = None


class DocumentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    original_filename: str
    file_type: str
    status: str
    created_at: datetime
