"""Common API response models."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    trace_id: str


class HealthResponse(BaseModel):
    status: str = Field(description="Service status")
    service: str
    version: str
    environment: str
    trace_id: str
