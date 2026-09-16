"""Search and question-answering API contracts."""

from pydantic import BaseModel, Field, field_validator


class RetrievalRequest(BaseModel):
    # 文档列表仅用于缩小本次检索范围，不是权限凭证；服务端仍会套用授权范围。
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    top_k: int = Field(default=4, ge=1, le=20)

    @field_validator("document_ids")
    @classmethod
    def unique_document_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(value))


class SearchRequest(RetrievalRequest):
    query: str = Field(min_length=1, max_length=8000)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query 不能为空")
        return value


class ChatRequest(RetrievalRequest):
    question: str = Field(min_length=1, max_length=8000)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question 不能为空")
        return value


class RetrievalHit(BaseModel):
    citation_id: int | None = None
    document_id: str | None = None
    source: str
    content: str
    type: str | None = None
    title: str | None = None
    page: int | None = None
    row: int | None = None
    chunk_index: int | None = None
    score: float
    vector_score: float
    bm25_score: float
    rerank_score: float | None = None
    rank_reason: str


class TokenUsageResponse(BaseModel):
    # 分开记录查询改写和答案生成，方便定位 token 成本来自哪一步。
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    query_rewrite: dict[str, int]
    answer_generation: dict[str, int]
    context_estimated_tokens: int = Field(ge=0)


class SearchResponse(BaseModel):
    query: str
    hits: list[RetrievalHit]
    count: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    trace_id: str


class ChatResponse(BaseModel):
    answer: str
    rewritten_query: str
    refused: bool
    sources: list[RetrievalHit]
    latency_ms: int = Field(ge=0)
    token_usage: TokenUsageResponse
    context_truncated: bool
    trace_id: str
