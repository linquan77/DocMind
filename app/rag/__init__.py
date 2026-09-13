"""Public RAG interfaces for the API and future agents."""

from app.rag.retriever import (
    HybridRetriever,
    RetrievalResult,
    RetrievalScope,
    get_retriever,
)

__all__ = [
    "HybridRetriever",
    "RetrievalResult",
    "RetrievalScope",
    "get_retriever",
]
