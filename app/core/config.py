"""Runtime configuration for the FastAPI service.

The existing project keeps its first-stage configuration in the repository root.
This module provides a typed, service-oriented view of the same environment
variables without forcing the API process to import the heavy RAG components at
startup.
"""

from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class Settings(BaseModel):
    """Application settings loaded from ``.env`` and process environment."""

    app_name: str = Field(default="Docmind API")
    app_version: str = Field(default="0.2.0")
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    cors_origins: list[str] = Field(default_factory=lambda: DEFAULT_CORS_ORIGINS.copy())
    database_url: str = Field(default="sqlite:///./docmind.db")
    mediawiki_api_url: str = "https://oxygennotincluded.wiki.gg/zh/api.php"
    mediawiki_base_url: str = "https://oxygennotincluded.wiki.gg/zh"
    mediawiki_language: str = "zh"
    mediawiki_root_categories: list[str] = Field(default_factory=lambda: ["建筑", "小动物"])
    mediawiki_excluded_category_keywords: list[str] = Field(
        default_factory=lambda: [
            "调试",
            "未实装",
            "未使用",
            "已移除",
            "开发者",
            "Debug",
            "Unused",
            "Unimplemented",
        ]
    )
    mediawiki_snapshot_path: str = "./data/raw/wiki"
    mediawiki_request_timeout: float = 30.0
    mediawiki_user_agent: str = "Docmind/0.2 (non-commercial learning project)"
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    deepseek_model: str = "deepseek-v4-pro"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    chroma_db_path: str = "./chroma_db"
    model_cache_path: str = "./models"
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 4
    vector_top_k: int = 12
    bm25_top_k: int = 12
    reranker_candidate_k: int = 20
    reranker_score_threshold: float = 0.2
    vector_weight: float = 0.6
    bm25_weight: float = 0.4
    enable_reranker: bool = True
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_weight: float = 0.7
    enable_query_rewrite: bool = True
    context_max_tokens: int = 6000


def _load_values() -> dict[str, str]:
    # 先读取项目 .env，再用进程环境变量覆盖，满足容器和 CI 的注入需求。
    values = {
        key: value
        for key, value in dotenv_values(PROJECT_ROOT / ".env").items()
        if value is not None
    }
    # 进程环境变量优先级更高，生产环境无需修改仓库中的配置文件。
    import os

    for key in (
        "APP_NAME",
        "APP_VERSION",
        "ENVIRONMENT",
        "LOG_LEVEL",
        "CORS_ORIGINS",
        "DATABASE_URL",
        "MEDIAWIKI_API_URL",
        "MEDIAWIKI_BASE_URL",
        "MEDIAWIKI_LANGUAGE",
        "MEDIAWIKI_ROOT_CATEGORIES",
        "MEDIAWIKI_EXCLUDED_CATEGORY_KEYWORDS",
        "MEDIAWIKI_SNAPSHOT_PATH",
        "MEDIAWIKI_REQUEST_TIMEOUT",
        "MEDIAWIKI_USER_AGENT",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "EMBEDDING_MODEL",
        "CHROMA_DB_PATH",
        "MODEL_CACHE_PATH",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
        "TOP_K",
        "VECTOR_TOP_K",
        "BM25_TOP_K",
        "RERANKER_CANDIDATE_K",
        "RERANKER_SCORE_THRESHOLD",
        "VECTOR_WEIGHT",
        "BM25_WEIGHT",
        "ENABLE_RERANKER",
        "RERANKER_MODEL",
        "RERANKER_WEIGHT",
        "ENABLE_QUERY_REWRITE",
        "CONTEXT_MAX_TOKENS",
    ):
        if key in os.environ:
            values[key] = os.environ[key]
    return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 配置在进程内只解析一次；测试需要切换环境时可显式 cache_clear()。
    values = _load_values()

    def as_bool(key: str, default: bool) -> bool:
        return values.get(key, str(default)).lower() == "true"

    def as_csv(key: str, default: list[str]) -> list[str]:
        # 用逗号分隔环境变量，便于不同部署环境配置多个可信前端域名。
        raw_value = values.get(key)
        if raw_value is None:
            return default.copy()
        return [item.strip() for item in raw_value.split(",") if item.strip()]

    return Settings(
        app_name=values.get("APP_NAME", "Docmind API"),
        app_version=values.get("APP_VERSION", "0.2.0"),
        environment=values.get("ENVIRONMENT", "development"),
        log_level=values.get("LOG_LEVEL", "INFO"),
        cors_origins=as_csv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS),
        database_url=values.get("DATABASE_URL", "sqlite:///./docmind.db"),
        mediawiki_api_url=values.get(
            "MEDIAWIKI_API_URL", "https://oxygennotincluded.wiki.gg/zh/api.php"
        ),
        mediawiki_base_url=values.get(
            "MEDIAWIKI_BASE_URL", "https://oxygennotincluded.wiki.gg/zh"
        ),
        mediawiki_language=values.get("MEDIAWIKI_LANGUAGE", "zh"),
        mediawiki_root_categories=as_csv("MEDIAWIKI_ROOT_CATEGORIES", ["建筑", "小动物"]),
        mediawiki_excluded_category_keywords=as_csv(
            "MEDIAWIKI_EXCLUDED_CATEGORY_KEYWORDS",
            ["调试", "未实装", "未使用", "已移除", "开发者", "Debug", "Unused", "Unimplemented"],
        ),
        mediawiki_snapshot_path=values.get("MEDIAWIKI_SNAPSHOT_PATH", "./data/raw/wiki"),
        mediawiki_request_timeout=float(values.get("MEDIAWIKI_REQUEST_TIMEOUT", 30)),
        mediawiki_user_agent=values.get(
            "MEDIAWIKI_USER_AGENT", "Docmind/0.2 (non-commercial learning project)"
        ),
        deepseek_api_key=values.get("DEEPSEEK_API_KEY"),
        deepseek_base_url=values.get("DEEPSEEK_BASE_URL"),
        deepseek_model=values.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        embedding_model=values.get("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
        chroma_db_path=values.get("CHROMA_DB_PATH", "./chroma_db"),
        model_cache_path=values.get("MODEL_CACHE_PATH", "./models"),
        chunk_size=int(values.get("CHUNK_SIZE", 500)),
        chunk_overlap=int(values.get("CHUNK_OVERLAP", 50)),
        top_k=int(values.get("TOP_K", 4)),
        vector_top_k=int(values.get("VECTOR_TOP_K", 12)),
        bm25_top_k=int(values.get("BM25_TOP_K", 12)),
        reranker_candidate_k=int(values.get("RERANKER_CANDIDATE_K", 20)),
        reranker_score_threshold=float(values.get("RERANKER_SCORE_THRESHOLD", 0.2)),
        vector_weight=float(values.get("VECTOR_WEIGHT", 0.6)),
        bm25_weight=float(values.get("BM25_WEIGHT", 0.4)),
        enable_reranker=as_bool("ENABLE_RERANKER", True),
        reranker_model=values.get("RERANKER_MODEL", "BAAI/bge-reranker-base"),
        reranker_weight=float(values.get("RERANKER_WEIGHT", 0.7)),
        enable_query_rewrite=as_bool("ENABLE_QUERY_REWRITE", True),
        context_max_tokens=int(values.get("CONTEXT_MAX_TOKENS", 6000)),
    )
