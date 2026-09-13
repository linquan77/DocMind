"""Compatibility exports for first-stage scripts.

New application code reads settings from :mod:`app.core.config`.
"""

from app.core.config import get_settings


_settings = get_settings()

DEEPSEEK_API_KEY = _settings.deepseek_api_key
DEEPSEEK_BASE_URL = _settings.deepseek_base_url
DEEPSEEK_MODEL = _settings.deepseek_model
EMBEDDING_MODEL = _settings.embedding_model
CHROMA_DB_PATH = _settings.chroma_db_path
MODEL_CACHE_PATH = _settings.model_cache_path
CHUNK_SIZE = _settings.chunk_size
CHUNK_OVERLAP = _settings.chunk_overlap
TOP_K = _settings.top_k
VECTOR_TOP_K = _settings.vector_top_k
BM25_TOP_K = _settings.bm25_top_k
RERANKER_CANDIDATE_K = _settings.reranker_candidate_k
RERANKER_SCORE_THRESHOLD = _settings.reranker_score_threshold
VECTOR_WEIGHT = _settings.vector_weight
BM25_WEIGHT = _settings.bm25_weight
ENABLE_RERANKER = _settings.enable_reranker
RERANKER_MODEL = _settings.reranker_model
RERANKER_WEIGHT = _settings.reranker_weight
ENABLE_QUERY_REWRITE = _settings.enable_query_rewrite
CONTEXT_MAX_TOKENS = _settings.context_max_tokens
