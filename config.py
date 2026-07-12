import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL")
DEEPSEEK_MODEL    = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
EMBEDDING_MODEL   = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
CHROMA_DB_PATH    = os.getenv("CHROMA_DB_PATH", "./chroma_db")
MODEL_CACHE_PATH  = os.getenv("MODEL_CACHE_PATH", "./models")
CHUNK_SIZE        = int(os.getenv("CHUNK_SIZE", 500))
CHUNK_OVERLAP     = int(os.getenv("CHUNK_OVERLAP", 50))
TOP_K             = int(os.getenv("TOP_K", 4))

# 第一阶段 RAG 检索参数
VECTOR_TOP_K      = int(os.getenv("VECTOR_TOP_K", 12))
BM25_TOP_K        = int(os.getenv("BM25_TOP_K", 12))
RERANKER_CANDIDATE_K = int(os.getenv("RERANKER_CANDIDATE_K", 20))
RERANKER_SCORE_THRESHOLD = float(os.getenv("RERANKER_SCORE_THRESHOLD", 0.2))
VECTOR_WEIGHT     = float(os.getenv("VECTOR_WEIGHT", 0.6))
BM25_WEIGHT       = float(os.getenv("BM25_WEIGHT", 0.4))
ENABLE_RERANKER   = os.getenv("ENABLE_RERANKER", "true").lower() == "true"
RERANKER_MODEL    = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
RERANKER_WEIGHT   = float(os.getenv("RERANKER_WEIGHT", 0.7))
ENABLE_QUERY_REWRITE = os.getenv("ENABLE_QUERY_REWRITE", "true").lower() == "true"
