"""Application exceptions and consistent HTTP error responses."""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import trace_id_context


class AppError(Exception):
    """A safe, expected error that can be shown to an API client."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "application_error",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


def _error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        },
        "trace_id": trace_id_context.get(),
    }
    if details is not None:
        body["error"]["details"] = details
    return body


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.code, exc.message, exc.details),
    )


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_body("validation_error", "请求参数校验失败", exc.errors()),
    )


async def unhandled_error_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=_error_body("internal_server_error", "服务器内部错误"),
    )
