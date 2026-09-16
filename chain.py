"""Compatibility wrapper for Streamlit and first-stage evaluations."""

# 新代码应优先调用 app.rag 与 app.services；此处保留旧入口以便 Streamlit 平滑迁移。

from typing import Any

from app.rag.context import ContextBuilder
from app.rag.retriever import RetrievalResult
from app.services.qa_service import get_qa_service, retrieval_result_to_dict


def format_evidence(results: list[RetrievalResult]) -> str:
    return ContextBuilder().build(results).text


class QAChain:
    def __init__(self):
        self.service = get_qa_service()

    def invoke(self, inputs: Any) -> dict[str, Any]:
        if isinstance(inputs, str):
            question = inputs
            metadata_filter = None
            top_k = None
        else:
            question = inputs.get("question") or inputs.get("query") or ""
            metadata_filter = inputs.get("metadata_filter")
            top_k = inputs.get("top_k")

        result = self.service.answer(
            question,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )
        return {
            "answer": result.answer,
            "sources": result.sources,
            "rewritten_query": result.rewritten_query,
            "refused": result.refused,
            "latency_ms": result.latency_ms,
            "retrieval": [retrieval_result_to_dict(item) for item in result.results],
            "token_usage": {
                **result.token_usage.as_dict(),
                "query_rewrite": result.rewrite_usage.as_dict(),
                "answer_generation": result.generation_usage.as_dict(),
                "context_estimated_tokens": result.context_estimated_tokens,
            },
            "context_truncated": result.context_truncated,
        }


def get_qa_chain() -> QAChain:
    return QAChain()
