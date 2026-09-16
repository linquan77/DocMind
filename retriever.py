"""Compatibility exports for first-stage scripts."""

# 面向 API 或 Agent 的新代码应使用 get_retriever().search(query, top_k=...)。

from app.rag.embeddings import get_embeddings
from app.rag.retriever import (
    HybridRetriever,
    RetrievalResult,
    RetrievalScope,
    SimpleBM25,
    get_retriever,
)

__all__ = [
    "HybridRetriever",
    "RetrievalResult",
    "RetrievalScope",
    "SimpleBM25",
    "get_embeddings",
    "get_retriever",
]
