"""Build cited, token-bounded context for answer generation."""

from dataclasses import dataclass
import logging
import re

from app.core.config import get_settings
from app.rag.retriever import RetrievalResult


logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Return a deterministic approximation when the model tokenizer is unavailable."""

    # 不绑定特定模型 tokenizer，按中文字符、英文词和符号估算，结果用于上下文预算而非计费。
    units = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+|[^\s]", text or "")
    return len(units)


def source_location(metadata: dict) -> str:
    document_type = metadata.get("type")
    if document_type == "price_table":
        return f"第 {metadata.get('row', '?')} 行"
    if document_type == "price_summary":
        return "商品汇总"
    if document_type == "html":
        title = metadata.get("title")
        chunk_index = metadata.get("chunk_index")
        location = f"HTML 页面「{title}」" if title else "HTML 页面"
        if chunk_index is not None:
            location += f"，切块 {int(chunk_index) + 1}"
        return location
    page = metadata.get("page")
    return f"第 {page} 页" if page is not None else "未知位置"


@dataclass(frozen=True)
class ContextBundle:
    text: str
    results: list[RetrievalResult]
    estimated_tokens: int
    truncated: bool


class ContextBuilder:
    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens or get_settings().context_max_tokens

    def build(self, results: list[RetrievalResult]) -> ContextBundle:
        blocks: list[str] = []
        selected: list[RetrievalResult] = []
        token_count = 0
        truncated = False

        for citation_id, result in enumerate(results, start=1):
            # 检索顺序直接映射为引用编号，保证提示词、回答和响应来源使用同一编号。
            metadata = result.doc.metadata
            block = (
                f"[{citation_id}] 来源：{metadata.get('source', '未知文件')}，"
                f"位置：{source_location(metadata)}，相关度：{result.score:.3f}\n"
                f"{result.doc.page_content}"
            )
            block_tokens = estimate_tokens(block)
            if blocks and token_count + block_tokens > self.max_tokens:
                # 保留完整切块，不在句子中间硬截断；剩余候选通过 truncated 标记体现。
                truncated = True
                break

            # 将各阶段分数写回来源元数据，兼容旧 Streamlit 展示并便于 Agent 调试。
            metadata["citation_id"] = citation_id
            metadata["score"] = result.score
            metadata["vector_score"] = result.vector_score
            metadata["bm25_score"] = result.bm25_score
            metadata["rerank_score"] = result.rerank_score
            metadata["rank_reason"] = result.rank_reason
            blocks.append(block)
            selected.append(result)
            token_count += block_tokens

        logger.info(
            "context built candidates=%d selected=%d estimated_tokens=%d truncated=%s",
            len(results),
            len(selected),
            token_count,
            truncated,
        )
        return ContextBundle(
            text="\n\n".join(blocks),
            results=selected,
            estimated_tokens=token_count,
            truncated=truncated,
        )
