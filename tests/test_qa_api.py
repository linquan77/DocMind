from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.api import chat as chat_api
from app.main import app
from app.rag.context import ContextBuilder, ContextBundle
from app.rag.generator import GenerationResult, RewriteResult, TokenUsage
from app.rag.retriever import HybridRetriever, RetrievalResult, RetrievalScope
from app.services.qa_service import QAResult, QAService, SearchExecution


def sample_result() -> RetrievalResult:
    return RetrievalResult(
        doc=Document(
            page_content="系统支持本地 HTML 文件问答。",
            metadata={
                "document_id": "doc-html-1",
                "source": "guide.html",
                "type": "html",
                "title": "使用指南",
                "page": 3,
                "chunk_index": 0,
                "citation_id": 1,
            },
        ),
        score=0.91,
        vector_score=0.82,
        bm25_score=0.73,
        rerank_score=0.96,
        rank_reason="vector=0.820, bm25=0.730, reranker=0.960",
    )


def test_search_endpoint_preserves_source_page_and_scores(monkeypatch):
    result = sample_result()

    def fake_search(query, **_kwargs):
        return SearchExecution(query=query, results=[result], latency_ms=12)

    monkeypatch.setattr(chat_api, "search_documents", fake_search)
    with TestClient(app) as client:
        response = client.post(
            "/search",
            json={"query": "支持 HTML 吗？", "document_ids": ["doc-html-1"], "top_k": 10},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["hits"][0]["source"] == "guide.html"
    assert body["hits"][0]["page"] == 3
    assert body["hits"][0]["score"] == 0.91
    assert body["hits"][0]["rerank_score"] == 0.96
    assert body["trace_id"] == response.headers["X-Trace-ID"]


def test_chat_endpoint_returns_token_statistics(monkeypatch):
    result = sample_result()
    qa_result = QAResult(
        answer="支持本地 HTML 文件问答。[1]",
        rewritten_query="本地 HTML 文件问答支持",
        refused=False,
        results=[result],
        latency_ms=35,
        rewrite_usage=TokenUsage(input_tokens=8, output_tokens=4, total_tokens=12),
        generation_usage=TokenUsage(input_tokens=30, output_tokens=10, total_tokens=40),
        context_estimated_tokens=18,
        context_truncated=False,
    )
    monkeypatch.setattr(chat_api, "answer_question", lambda *_args, **_kwargs: qa_result)

    with TestClient(app) as client:
        response = client.post("/chat", json={"question": "支持 HTML 吗？"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "支持本地 HTML 文件问答。[1]"
    assert body["token_usage"]["total_tokens"] == 52
    assert body["token_usage"]["context_estimated_tokens"] == 18
    assert body["sources"][0]["citation_id"] == 1


def test_permission_scope_uses_selection_and_authorization_intersection():
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.settings = SimpleNamespace(top_k=4)
    retriever._load_all_documents = lambda _filter: (_ for _ in ()).throw(
        AssertionError("empty permission scope must stop before loading documents")
    )
    scope = RetrievalScope(
        selected_document_ids=frozenset({"selected-document"}),
        allowed_document_ids=frozenset({"different-authorized-document"}),
    )

    assert retriever.search("test", scope=scope) == []


def test_context_builder_preserves_citation_and_rerank_metadata():
    result = sample_result()
    bundle = ContextBuilder(max_tokens=1000).build([result])

    assert "guide.html" in bundle.text
    assert result.doc.metadata["citation_id"] == 1
    assert result.doc.metadata["rerank_score"] == 0.96
    assert bundle.estimated_tokens > 0


def test_qa_service_orchestrates_rewrite_retrieve_context_and_generate():
    events = []
    result = sample_result()

    class FakeRewriter:
        def rewrite(self, question):
            events.append(("rewrite", question))
            return RewriteResult("改写后的问题", TokenUsage(total_tokens=3), 1)

    class FakeRetriever:
        def search(self, query, **_kwargs):
            events.append(("retrieve", query))
            return [result]

    class FakeContextBuilder:
        def build(self, results):
            events.append(("context", len(results)))
            return ContextBundle("证据上下文", results, 8, False)

    class FakeGenerator:
        def generate(self, question, context):
            events.append(("generate", question, context))
            return GenerationResult("回答。[1]", TokenUsage(total_tokens=5), 2)

    service = QAService(
        retriever=FakeRetriever(),
        context_builder=FakeContextBuilder(),
        query_rewriter=FakeRewriter(),
        answer_generator=FakeGenerator(),
    )
    answer = service.answer("原始问题")

    assert [event[0] for event in events] == ["rewrite", "retrieve", "context", "generate"]
    assert answer.answer == "回答。[1]"
    assert answer.token_usage.total_tokens == 8
