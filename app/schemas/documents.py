"""Document API schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    # 允许 Pydantic 直接从 SQLAlchemy 对象读取字段，路由层无需手工拼装字典。
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str | None = None
    size_bytes: int = Field(ge=0)
    status: str
    chunk_count: int = Field(ge=0)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class DocumentDeleteResponse(BaseModel):
    id: str
    filename: str
    deleted_chunks: int = Field(ge=0)
    message: str
    trace_id: str
