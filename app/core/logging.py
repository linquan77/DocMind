"""Logging setup and trace ID context."""

from contextvars import ContextVar
import logging


# ContextVar 能在异步任务之间隔离请求上下文，asyncio.to_thread() 也会复制当前上下文。
trace_id_context: ContextVar[str] = ContextVar("trace_id", default="-")


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # 给每条日志动态补充 trace_id，业务模块无需重复传递该参数。
        record.trace_id = trace_id_context.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure one predictable console handler for the API process."""

    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [trace_id=%(trace_id)s] "
                "%(name)s: %(message)s"
            )
        )
        handler.addFilter(TraceIdFilter())
        root_logger.addHandler(handler)
