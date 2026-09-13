"""Health endpoint."""

from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.core.logging import trace_id_context
from app.schemas.common import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="服务健康检查")
async def health(request: Request) -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        trace_id=trace_id_context.get(),
    )
