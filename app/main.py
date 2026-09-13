"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.health import router as health_router
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.exceptions import (
    AppError,
    app_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging, trace_id_context
from fastapi.exceptions import RequestValidationError


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    logging.getLogger(__name__).info("starting %s", settings.app_name)
    yield
    logging.getLogger(__name__).info("stopping %s", settings.app_name)


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Docmind RAG service API",
    lifespan=lifespan,
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    incoming_trace_id = request.headers.get("X-Trace-ID")
    trace_id = incoming_trace_id or str(uuid4())
    token = trace_id_context.set(trace_id)
    try:
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        trace_id_context.reset(token)


app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(chat_router)
