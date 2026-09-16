"""Application-level orchestration for search and grounded question answering."""

from dataclasses import dataclass
import logging
import time
from typing import Any

from langchain_core.documents import Document

from app.rag.context import ContextBuilder
from app.rag.generator import AnswerGenerator, QueryRewriter, TokenUsage
from app.rag.retriever import (
    HybridRetriever,
    MetadataFilter,
    RetrievalResult,
    RetrievalScope,
    get_retriever,
)


logger = logging.getLogger(__name__)
REFUSAL_TEXT = "文档中未找到相关信息。"


@dataclass(frozen=True)
class SearchExecution:
    query: str
    results: list[RetrievalResult]
    latency_ms: int


@dataclass(frozen=True)
class QAResult:
    answer: str
    rewritten_query: str
    refused: bool
    results: list[RetrievalResult]
    latency_ms: int
    rewrite_usage: TokenUsage
    generation_usage: TokenUsage
    context_estimated_tokens: int
    context_truncated: bool

    @property
    def token_usage(self) -> TokenUsage:
        return self.rewrite_usage + self.generation_usage

    @property
    def sources(self) -> list[Document]:
        return [result.doc for result in self.results]


def build_scope(
    *,
    selected_document_ids: list[str] | None = None,
    allowed_document_ids: set[str] | None = None,
) -> RetrievalScope | None:
    # selected_document_ids 只是用户本次选择的范围；真正的权限边界由服务端allowed_document_ids 决定。检索器会在两者同时存在时取交集。
    if selected_document_ids is None and allowed_document_ids is None:
        return None
    return RetrievalScope(
        selected_document_ids=(
            frozenset(selected_document_ids) if selected_document_ids is not None else None
        ),
        allowed_document_ids=(
            frozenset(allowed_document_ids) if allowed_document_ids is not None else None
        ),
    )


def retrieval_result_to_dict(result: RetrievalResult) -> dict[str, Any]:
    # 固定检索结果的对外结构，让 /search、/chat 和未来 Agent 工具都能稳定拿到来源、页码及各阶段分数，而不依赖内部 Document 实现。
    metadata = result.doc.metadata
    return {
        "citation_id": metadata.get("citation_id"),
        "document_id": metadata.get("document_id"),
        "source": metadata.get("source", "未知文件"),
        "content": result.doc.page_content,
        "type": metadata.get("type"),
        "title": metadata.get("title"),
        "page": metadata.get("page"),
        "row": metadata.get("row"),
        "chunk_index": metadata.get("chunk_index"),
        "score": result.score,
        "vector_score": result.vector_score,
        "bm25_score": result.bm25_score,
        "rerank_score": result.rerank_score,
        "rank_reason": result.rank_reason,
    }


class QAService:
    def __init__(
        self,
        retriever: HybridRetriever | None = None,
        context_builder: ContextBuilder | None = None,
        query_rewriter: QueryRewriter | None = None,
        answer_generator: AnswerGenerator | None = None,
    ) -> None:
        # 依赖支持注入，便于测试时替换模型，也方便未来 Agent 直接复用检索模块。
        self.retriever = retriever or get_retriever()
        self.context_builder = context_builder or ContextBuilder()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.answer_generator = answer_generator or AnswerGenerator()

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        selected_document_ids: list[str] | None = None,
        allowed_document_ids: set[str] | None = None,
        metadata_filter: MetadataFilter = None,
    ) -> SearchExecution:
        # 搜索用例只执行独立检索链路，不调用大模型生成答案。
        started = time.perf_counter()
        scope = build_scope(
            selected_document_ids=selected_document_ids,
            allowed_document_ids=allowed_document_ids,
        )
        results = self.retriever.search(
            query,
            top_k=top_k,
            scope=scope,
            metadata_filter=metadata_filter,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info("search use case completed results=%d latency_ms=%d", len(results), latency_ms)
        return SearchExecution(query=query, results=results, latency_ms=latency_ms)

    def answer(
        self,
        question: str,
        *,
        top_k: int | None = None,
        selected_document_ids: list[str] | None = None,
        allowed_document_ids: set[str] | None = None,
        metadata_filter: MetadataFilter = None,
    ) -> QAResult:
        # 完整问答链路：查询改写 → 独立检索 → 证据判断 → 上下文构造 → 答案生成。
        started = time.perf_counter()
        rewrite = self.query_rewriter.rewrite(question)
        search = self.search(
            rewrite.query,
            top_k=top_k,
            selected_document_ids=selected_document_ids,
            allowed_document_ids=allowed_document_ids,
            metadata_filter=metadata_filter,
        )
        if not search.results:
            # 没有可信证据时直接拒答，避免模型脱离文档自由发挥。
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.info("answer refused reason=no_evidence latency_ms=%d", latency_ms)
            return QAResult(
                answer=REFUSAL_TEXT,
                rewritten_query=rewrite.query,
                refused=True,
                results=[],
                latency_ms=latency_ms,
                rewrite_usage=rewrite.token_usage,
                generation_usage=TokenUsage(),
                context_estimated_tokens=0,
                context_truncated=False,
            )

        # 上下文构造阶段统一分配引用编号并控制 token 预算。
        context = self.context_builder.build(search.results)
        generation = self.answer_generator.generate(question, context.text)
        latency_ms = int((time.perf_counter() - started) * 1000)
        refused = generation.answer.strip().startswith("文档中未找到相关信息")
        logger.info(
            "answer use case completed refused=%s sources=%d latency_ms=%d total_tokens=%d",
            refused,
            len(context.results),
            latency_ms,
            (rewrite.token_usage + generation.token_usage).total_tokens,
        )
        return QAResult(
            answer=generation.answer,
            rewritten_query=rewrite.query,
            refused=refused,
            results=context.results,
            latency_ms=latency_ms,
            rewrite_usage=rewrite.token_usage,
            generation_usage=generation.token_usage,
            context_estimated_tokens=context.estimated_tokens,
            context_truncated=context.truncated,
        )


def get_qa_service() -> QAService:
    return QAService()


def search_documents(
    query: str,
    *,
    top_k: int | None = None,
    selected_document_ids: list[str] | None = None,
    allowed_document_ids: set[str] | None = None,
) -> SearchExecution:
    return get_qa_service().search(
        query,
        top_k=top_k,
        selected_document_ids=selected_document_ids,
        allowed_document_ids=allowed_document_ids,
    )


def answer_question(
    question: str,
    *,
    top_k: int | None = None,
    selected_document_ids: list[str] | None = None,
    allowed_document_ids: set[str] | None = None,
) -> QAResult:
    return get_qa_service().answer(
        question,
        top_k=top_k,
        selected_document_ids=selected_document_ids,
        allowed_document_ids=allowed_document_ids,
    )
