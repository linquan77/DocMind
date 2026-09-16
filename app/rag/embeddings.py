"""Embedding model construction."""

from functools import lru_cache
import logging
import os
import time

from langchain_community.embeddings import HuggingFaceEmbeddings

from app.core.config import get_settings


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    # 模型加载成本较高，进程内复用同一个实例，避免每次上传或查询都重新加载。
    settings = get_settings()
    # 统一缓存目录，保证本地运行和 Docker 挂载使用同一份模型文件。
    os.environ.setdefault("HF_HOME", settings.model_cache_path)
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", settings.model_cache_path)
    started = time.perf_counter()
    embeddings = HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        cache_folder=settings.model_cache_path,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    logger.info(
        "embedding model loaded model=%s latency_ms=%d",
        settings.embedding_model,
        int((time.perf_counter() - started) * 1000),
    )
    return embeddings
