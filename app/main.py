"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

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
    # 生命周期钩子只在服务启动/停止时执行，适合初始化数据库和全局日志。
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
    # 优先沿用调用方传入的 trace ID；没有时生成新的 ID，便于串联一次请求的全部日志。
    incoming_trace_id = request.headers.get("X-Trace-ID")
    trace_id = incoming_trace_id or str(uuid4())
    token = trace_id_context.set(trace_id)
    try:
        response = await call_next(request)
        # 将 trace ID 返回给调用方，排查问题时可直接用它检索服务日志。
        response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        trace_id_context.reset(token)


# CORS 放在应用最外层，使浏览器预检请求和异常响应也能返回跨域响应头。
# 仅允许配置中的可信前端来源，不使用生产环境风险较高的通配符来源。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-ID"],
)

# 所有路由共用同一套错误结构，避免每个接口重复拼装错误响应。
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
# 路由按业务域拆分，main.py 只负责组装应用。
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(chat_router)
