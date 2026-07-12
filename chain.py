import time
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from config import *
from retriever import RetrievalResult, get_retriever


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


def format_evidence(results: List[RetrievalResult]) -> str:
    blocks = []
    for index, item in enumerate(results, start=1):
        metadata = item.doc.metadata
        source = metadata.get("source", "未知文件")
        if metadata.get("type") in ["price_table", "price_summary"]:
            row = metadata.get("row")
            location = f"第 {row} 行" if row else "商品汇总"
        else:
            page = metadata.get("page")
            location = f"第 {page} 页" if page is not None else "未知位置"

        blocks.append(
            f"[{index}] 来源：{source}，位置：{location}，相关度：{item.score:.3f}\n"
            f"{item.doc.page_content}"
        )
        metadata["citation_id"] = index
        metadata["score"] = item.score
        metadata["rank_reason"] = item.rank_reason
    return "\n\n".join(blocks)


class QAChain:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=DEEPSEEK_MODEL,
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            streaming=True,
        )
        self.retriever = get_retriever()

    def invoke(self, inputs: Any) -> Dict[str, Any]:
        if isinstance(inputs, str):
            question = inputs
            metadata_filter = None
        else:
            question = inputs.get("question") or inputs.get("query") or ""
            metadata_filter = inputs.get("metadata_filter")

        start = time.perf_counter()
        rewritten_query = self._rewrite_query(question)
        retrieval_results = self.retriever.retrieve(
            rewritten_query,
            metadata_filter=metadata_filter,
            top_k=TOP_K,
        )

        if not retrieval_results:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {
                "answer": "文档中未找到相关信息。",
                "sources": [],
                "rewritten_query": rewritten_query,
                "refused": True,
                "latency_ms": latency_ms,
                "retrieval": [],
            }

        context = format_evidence(retrieval_results)
        answer = (
            ANSWER_PROMPT
            | self.llm
            | StrOutputParser()
        ).invoke({"context": context, "question": question})

        latency_ms = int((time.perf_counter() - start) * 1000)
        refused = answer.strip().startswith("文档中未找到相关信息")
        return {
            "answer": answer,
            "sources": [item.doc for item in retrieval_results],
            "rewritten_query": rewritten_query,
            "refused": refused,
            "latency_ms": latency_ms,
            "retrieval": [
                {
                    "citation_id": item.doc.metadata.get("citation_id"),
                    "source": item.doc.metadata.get("source"),
                    "score": item.score,
                    "vector_score": item.vector_score,
                    "bm25_score": item.bm25_score,
                    "rerank_score": item.rerank_score,
                    "rank_reason": item.rank_reason,
                }
                for item in retrieval_results
            ],
        }

    def _rewrite_query(self, question: str) -> str:
        if not ENABLE_QUERY_REWRITE:
            return question
        try:
            rewritten = (
                REWRITE_PROMPT
                | self.llm
                | StrOutputParser()
            ).invoke({"question": question})
            rewritten = rewritten.strip()
            return rewritten or question
        except Exception:
            return question


def get_qa_chain():
    return QAChain()
