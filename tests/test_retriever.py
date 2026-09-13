from types import SimpleNamespace

from langchain_core.documents import Document

from app.rag import retriever as retriever_module
from app.rag.retriever import HybridRetriever, RetrievalScope


class FakeVectorStore:
    def __init__(self):
        self.ids = ["chunk-allowed", "chunk-denied"]
        self.documents = ["HTML 支持本地文件问答", "无权限访问的内部文档"]
        self.metadatas = [
            {
                "_chunk_id": "chunk-allowed",
                "document_id": "doc-allowed",
                "source": "guide.html",
                "page": 2,
            },
            {
                "_chunk_id": "chunk-denied",
                "document_id": "doc-denied",
                "source": "private.pdf",
                "page": 8,
            },
        ]

    def get(self, **_kwargs):
        return {
            "ids": self.ids,
            "documents": self.documents,
            "metadatas": self.metadatas,
        }

    def similarity_search_with_score(self, _query, **_kwargs):
        return [
            (Document(page_content=text, metadata=metadata), distance)
            for text, metadata, distance in zip(
                self.documents,
                self.metadatas,
                [0.1, 0.2],
            )
        ]


def test_public_search_enforces_permission_filter_and_preserves_metadata(monkeypatch):
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.settings = SimpleNamespace(
        top_k=4,
        vector_top_k=12,
        bm25_top_k=12,
        reranker_candidate_k=20,
        reranker_score_threshold=0.0,
        vector_weight=0.6,
        bm25_weight=0.4,
        reranker_weight=0.7,
    )
    retriever.vectorstore = FakeVectorStore()
    monkeypatch.setattr(retriever_module, "get_reranker", lambda: None)

    results = retriever.search(
        "HTML 问答",
        top_k=10,
        scope=RetrievalScope(allowed_document_ids=frozenset({"doc-allowed"})),
    )

    assert len(results) == 1
    assert results[0].doc.metadata["document_id"] == "doc-allowed"
    assert results[0].doc.metadata["source"] == "guide.html"
    assert results[0].doc.metadata["page"] == 2
    assert results[0].vector_score == 1.0
    assert results[0].rerank_score is None
