"""Lazy cross-encoder reranker."""

from functools import lru_cache
import logging
import time
from typing import Sequence

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    def __init__(self) -> None:
        settings = get_settings()
        # 延迟导入重模型依赖，使健康检查和普通管理接口无需加载模型。
        from sentence_transformers import CrossEncoder

        started = time.perf_counter()
        self.model = CrossEncoder(
            settings.reranker_model,
            device="cpu",
            cache_folder=settings.model_cache_path,
        )
        logger.info(
            "reranker loaded model=%s latency_ms=%d",
            settings.reranker_model,
            int((time.perf_counter() - started) * 1000),
        )

    def predict(self, query: str, texts: Sequence[str]) -> list[float]:
        started = time.perf_counter()
        pairs = [(query, text) for text in texts]
        scores = [float(score) for score in self.model.predict(pairs)]
        logger.info(
            "reranking completed candidates=%d latency_ms=%d",
            len(texts),
            int((time.perf_counter() - started) * 1000),
        )
        return scores


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoderReranker | None:
    # Reranker 是可选增强项；关闭或加载失败时继续使用向量+BM25结果，不中断服务。
    if not get_settings().enable_reranker:
        return None
    try:
        return CrossEncoderReranker()
    except Exception:
        logger.exception("reranker initialization failed; continuing without reranking")
        return None
