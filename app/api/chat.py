"""Independent retrieval and grounded chat endpoints."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.exceptions import AppError
from app.core.logging import trace_id_context
from app.core.security import get_allowed_document_ids
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    RetrievalHit,
    SearchRequest,
    SearchResponse,
    TokenUsageResponse,
)
from app.services.qa_service import (
    answer_question,
    retrieval_result_to_dict,
    search_documents,
)


router = APIRouter(tags=["rag"])
logger = logging.getLogger(__name__)


def _retrieval_hit(result) -> RetrievalHit:
    return RetrievalHit.model_validate(retrieval_result_to_dict(result))


@router.post("/search", response_model=SearchResponse, summary="独立检索文档切块")
async def search(
    request: SearchRequest,
    allowed_document_ids: Annotated[set[str] | None, Depends(get_allowed_document_ids)],
) -> SearchResponse:
    try:
        execution = await asyncio.to_thread(
            search_documents,
            request.query,
            top_k=request.top_k,
            selected_document_ids=request.document_ids,
            allowed_document_ids=allowed_document_ids,
        )
    except AppError:
        raise
    except Exception as exc:
        logger.exception("search endpoint failed")
        raise AppError(
            "文档检索失败",
            status_code=503,
            code="document_search_failed",
        ) from exc

    hits = [_retrieval_hit(result) for result in execution.results]
    return SearchResponse(
        query=execution.query,
        hits=hits,
        count=len(hits),
        latency_ms=execution.latency_ms,
        trace_id=trace_id_context.get(),
    )


@router.post("/chat", response_model=ChatResponse, summary="基于文档证据回答问题")
async def chat(
    request: ChatRequest,
    allowed_document_ids: Annotated[set[str] | None, Depends(get_allowed_document_ids)],
) -> ChatResponse:
    try:
        result = await asyncio.to_thread(
            answer_question,
            request.question,
            top_k=request.top_k,
            selected_document_ids=request.document_ids,
            allowed_document_ids=allowed_document_ids,
        )
    except AppError:
        raise
    except Exception as exc:
        logger.exception("chat endpoint failed")
        raise AppError(
            "问答生成失败",
            status_code=503,
            code="chat_generation_failed",
        ) from exc

    usage = result.token_usage
    return ChatResponse(
        answer=result.answer,
        rewritten_query=result.rewritten_query,
        refused=result.refused,
        sources=[_retrieval_hit(item) for item in result.results],
        latency_ms=result.latency_ms,
        token_usage=TokenUsageResponse(
            **usage.as_dict(),
            query_rewrite=result.rewrite_usage.as_dict(),
            answer_generation=result.generation_usage.as_dict(),
            context_estimated_tokens=result.context_estimated_tokens,
        ),
        context_truncated=result.context_truncated,
        trace_id=trace_id_context.get(),
    )
