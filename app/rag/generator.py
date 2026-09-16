"""Query rewriting and evidence-grounded answer generation."""

from dataclasses import dataclass
import logging
import time
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


logger = logging.getLogger(__name__)


REWRITE_PROMPT = PromptTemplate.from_template(
    """请把用户问题改写成适合知识库检索的独立查询。
要求：
1. 保留关键实体、时间、指标、文件名等信息。
2. 不要回答问题。
3. 只输出改写后的查询。

用户问题：{question}
"""
)

ANSWER_PROMPT = PromptTemplate.from_template(
    """你是一个严谨的知识库问答助手。只能根据【参考证据】回答。

规则：
1. 如果证据不足以回答问题，必须回答：文档中未找到相关信息。
2. 不要使用常识、猜测或编造的信息补全答案。
3. 每个关键结论后必须使用引用编号，例如 [1]、[2]。
4. 引用编号只能来自参考证据中已有的编号。
5. 用中文回答，语言简洁清楚。

【参考证据】
{context}

【用户问题】
{question}
"""
)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class RewriteResult:
    query: str
    token_usage: TokenUsage
    latency_ms: int


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    token_usage: TokenUsage
    latency_ms: int


def _create_llm() -> ChatOpenAI:
    settings = get_settings()
    # 当前接口返回完整 JSON，因此使用非流式调用；未来流式接口可复用相同提示词和统计结构。
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        streaming=False,
    )


def _message_text(message: BaseMessage) -> str:
    # 兼容模型返回纯字符串或内容块列表两种消息格式。
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
    return "".join(parts).strip()


def _token_usage(message: BaseMessage) -> TokenUsage:
    # 优先读取 LangChain 标准 usage_metadata，再兼容 OpenAI 风格 response_metadata。
    usage = getattr(message, "usage_metadata", None) or {}
    if usage:
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=int(usage.get("total_tokens") or input_tokens + output_tokens),
        )

    response_metadata: dict[str, Any] = getattr(message, "response_metadata", {}) or {}
    usage = response_metadata.get("token_usage", {}) or response_metadata.get("usage", {})
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens))
    return TokenUsage(input_tokens, output_tokens, total_tokens)


class QueryRewriter:
    def rewrite(self, question: str) -> RewriteResult:
        if not get_settings().enable_query_rewrite:
            return RewriteResult(question, TokenUsage(), 0)

        started = time.perf_counter()
        try:
            # 改写失败时回退原问题，检索仍可继续，避免非关键增强能力拖垮主链路。
            message = _create_llm().invoke(REWRITE_PROMPT.format(question=question))
            rewritten = _message_text(message) or question
            usage = _token_usage(message)
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "query rewrite completed latency_ms=%d total_tokens=%d",
                latency_ms,
                usage.total_tokens,
            )
            return RewriteResult(rewritten, usage, latency_ms)
        except Exception:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.exception("query rewrite failed; using original query latency_ms=%d", latency_ms)
            return RewriteResult(question, TokenUsage(), latency_ms)


class AnswerGenerator:
    def generate(self, question: str, context: str) -> GenerationResult:
        started = time.perf_counter()
        # 生成器只接收已经编号的证据，不直接访问向量库，保持模块边界清晰。
        message = _create_llm().invoke(ANSWER_PROMPT.format(context=context, question=question))
        answer = _message_text(message)
        usage = _token_usage(message)
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "answer generated latency_ms=%d total_tokens=%d",
            latency_ms,
            usage.total_tokens,
        )
        return GenerationResult(answer, usage, latency_ms)
