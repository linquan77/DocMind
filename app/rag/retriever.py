"""Hybrid vector and BM25 retrieval."""

from dataclasses import dataclass
import logging
import math
import re
import time
from typing import Any, Iterable

from langchain_core.documents import Document

from app.core.config import get_settings
from app.rag.reranker import get_reranker
from app.rag.vectorstore import get_vectorstore


MetadataFilter = dict[str, Any] | None
logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    doc: Document
    score: float
    vector_score: float = 0.0
    bm25_score: float = 0.0
    rerank_score: float | None = None
    rank_reason: str = ""


@dataclass(frozen=True)
class RetrievalScope:
    """Selection and authorization boundaries for one retrieval call.

    ``selected_document_ids`` comes from user intent. ``allowed_document_ids``
    must come from trusted authorization code. Their intersection is enforced
    before both vector and BM25 retrieval.
    """

    selected_document_ids: frozenset[str] | None = None
    allowed_document_ids: frozenset[str] | None = None

    def effective_document_ids(self) -> frozenset[str] | None:
        if self.selected_document_ids is None:
            return self.allowed_document_ids
        if self.allowed_document_ids is None:
            return self.selected_document_ids
        return self.selected_document_ids & self.allowed_document_ids


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    english_or_number = re.findall(r"[a-z0-9]+", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    chinese_bigrams = [
        "".join(chinese_chars[index : index + 2])
        for index in range(len(chinese_chars) - 1)
    ]
    return english_or_number + chinese_chars + chinese_bigrams


def _metadata_match(metadata: dict[str, Any], metadata_filter: MetadataFilter) -> bool:
    if not metadata_filter:
        return True
    for key, expected in metadata_filter.items():
        actual = metadata.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


def _build_chroma_filter(metadata_filter: MetadataFilter) -> MetadataFilter:
    if not metadata_filter:
        return None
    if len(metadata_filter) == 1:
        return metadata_filter
    return {"$and": [{key: value} for key, value in metadata_filter.items()]}


def _normalize_scores(items: Iterable[tuple[str, float]]) -> dict[str, float]:
    entries = list(items)
    if not entries:
        return {}
    values = [score for _, score in entries]
    minimum = min(values)
    maximum = max(values)
    if math.isclose(maximum, minimum):
        return {key: 1.0 for key, _ in entries}
    return {key: (score - minimum) / (maximum - minimum) for key, score in entries}


class SimpleBM25:
    def __init__(self, tokenized_documents: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.documents = tokenized_documents
        self.k1 = k1
        self.b = b
        self.average_length = sum(len(document) for document in self.documents) / max(
            len(self.documents), 1
        )
        self.document_frequency: dict[str, int] = {}
        for document in self.documents:
            for token in set(document):
                self.document_frequency[token] = self.document_frequency.get(token, 0) + 1

    def score(self, query_tokens: list[str], document_tokens: list[str]) -> float:
        if not query_tokens or not document_tokens:
            return 0.0
        frequencies: dict[str, int] = {}
        for token in document_tokens:
            frequencies[token] = frequencies.get(token, 0) + 1

        score = 0.0
        document_length = len(document_tokens)
        total_documents = max(len(self.documents), 1)
        for token in query_tokens:
            term_frequency = frequencies.get(token, 0)
            if term_frequency == 0:
                continue
            document_frequency = self.document_frequency.get(token, 0)
            inverse_document_frequency = math.log(
                1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = term_frequency + self.k1 * (
                1 - self.b + self.b * document_length / max(self.average_length, 1)
            )
            score += inverse_document_frequency * (
                term_frequency * (self.k1 + 1) / denominator
            )
        return score


class HybridRetriever:
    def __init__(self):
        self.settings = get_settings()
        self.vectorstore = get_vectorstore()

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        scope: RetrievalScope | None = None,
        metadata_filter: MetadataFilter = None,
    ) -> list[RetrievalResult]:
        started = time.perf_counter()
        requested_top_k = top_k or self.settings.top_k
        if not query.strip():
            raise ValueError("query must not be empty")
        if requested_top_k < 1:
            raise ValueError("top_k must be at least 1")
        if scope is not None:
            effective_ids = scope.effective_document_ids()
            if effective_ids is not None and not effective_ids:
                logger.info("retrieval denied by empty permission intersection")
                return []
            if effective_ids is not None:
                existing_document_filter = (metadata_filter or {}).get("document_id")
                if isinstance(existing_document_filter, dict) and "$in" in existing_document_filter:
                    effective_ids = effective_ids & frozenset(existing_document_filter["$in"])
                elif existing_document_filter is not None:
                    effective_ids = effective_ids & frozenset({str(existing_document_filter)})
                if not effective_ids:
                    logger.info("retrieval denied by document filter intersection")
                    return []
                metadata_filter = {
                    **(metadata_filter or {}),
                    "document_id": {"$in": sorted(effective_ids)},
                }

        logger.info(
            "retrieval started top_k=%d filtered=%s",
            requested_top_k,
            bool(metadata_filter),
        )
        all_documents = self._load_all_documents(metadata_filter)
        if not all_documents:
            logger.info("retrieval completed results=0 reason=no_accessible_documents")
            return []

        vector_hits = self._vector_search(query, metadata_filter)
        bm25_hits = self._bm25_search(query, all_documents)
        fused = self._fuse_results(vector_hits, bm25_hits, all_documents)
        reranked = self._rerank(query, fused[: self.settings.reranker_candidate_k])
        filtered = [
            result
            for result in reranked
            if result.score >= self.settings.reranker_score_threshold
        ]
        results = filtered[:requested_top_k]
        logger.info(
            "retrieval completed corpus=%d vector_hits=%d bm25_hits=%d results=%d latency_ms=%d",
            len(all_documents),
            len(vector_hits),
            len(bm25_hits),
            len(results),
            int((time.perf_counter() - started) * 1000),
        )
        return results

    def retrieve(
        self,
        query: str,
        metadata_filter: MetadataFilter = None,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Backward-compatible alias used by first-stage evaluations."""

        return self.search(query, top_k=top_k, metadata_filter=metadata_filter)

    def _load_all_documents(self, metadata_filter: MetadataFilter) -> dict[str, Document]:
        result = self.vectorstore.get(include=["documents", "metadatas"])
        documents: dict[str, Document] = {}
        for chunk_id, text, metadata in zip(
            result.get("ids", []),
            result.get("documents", []),
            result.get("metadatas", []),
        ):
            metadata = metadata or {}
            if _metadata_match(metadata, metadata_filter):
                documents[chunk_id] = Document(
                    page_content=text or "",
                    metadata={**metadata, "_chunk_id": chunk_id},
                )
        return documents

    def _vector_search(
        self, query: str, metadata_filter: MetadataFilter
    ) -> list[tuple[str, float]]:
        try:
            hits = self.vectorstore.similarity_search_with_score(
                query,
                k=self.settings.vector_top_k,
                filter=_build_chroma_filter(metadata_filter),
            )
        except TypeError:
            logger.warning("vector store filter API unavailable; applying filter after retrieval")
            hits = self.vectorstore.similarity_search_with_score(
                query, k=self.settings.vector_top_k
            )

        scored: list[tuple[str, float]] = []
        for document, distance in hits:
            if not _metadata_match(document.metadata, metadata_filter):
                continue
            chunk_id = document.metadata.get("_chunk_id") or self._find_chunk_id(document)
            if chunk_id:
                similarity = 1 / (1 + max(float(distance), 0.0))
                scored.append((chunk_id, similarity))
        return scored

    def _find_chunk_id(self, document: Document) -> str | None:
        result = self.vectorstore.get(
            where={"source": document.metadata.get("source", "")},
            include=["documents", "metadatas"],
        )
        for chunk_id, text in zip(result.get("ids", []), result.get("documents", [])):
            if text == document.page_content:
                return chunk_id
        return None

    def _bm25_search(
        self, query: str, documents: dict[str, Document]
    ) -> list[tuple[str, float]]:
        chunk_ids = list(documents)
        tokenized_documents = [_tokenize(documents[chunk_id].page_content) for chunk_id in chunk_ids]
        bm25 = SimpleBM25(tokenized_documents)
        query_tokens = _tokenize(query)
        scores = [
            (chunk_id, bm25.score(query_tokens, tokens))
            for chunk_id, tokens in zip(chunk_ids, tokenized_documents)
        ]
        return sorted(scores, key=lambda item: item[1], reverse=True)[: self.settings.bm25_top_k]

    def _fuse_results(
        self,
        vector_hits: list[tuple[str, float]],
        bm25_hits: list[tuple[str, float]],
        documents: dict[str, Document],
    ) -> list[RetrievalResult]:
        vector_scores = _normalize_scores(vector_hits)
        bm25_scores = _normalize_scores(bm25_hits)
        candidate_ids = (set(vector_scores) | set(bm25_scores)) & set(documents)
        results: list[RetrievalResult] = []
        for chunk_id in candidate_ids:
            vector_score = vector_scores.get(chunk_id, 0.0)
            bm25_score = bm25_scores.get(chunk_id, 0.0)
            combined_score = (
                self.settings.vector_weight * vector_score
                + self.settings.bm25_weight * bm25_score
            )
            results.append(
                RetrievalResult(
                    doc=documents[chunk_id],
                    score=combined_score,
                    vector_score=vector_score,
                    bm25_score=bm25_score,
                    rank_reason=f"vector={vector_score:.3f}, bm25={bm25_score:.3f}",
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)

    def _rerank(
        self, query: str, candidates: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        if not candidates:
            return candidates
        reranker = get_reranker()
        if reranker is None:
            return candidates

        raw_scores = reranker.predict(
            query, [candidate.doc.page_content for candidate in candidates]
        )
        normalized = _normalize_scores(
            (str(index), score) for index, score in enumerate(raw_scores)
        )
        for index, candidate in enumerate(candidates):
            rerank_score = normalized.get(str(index), 0.0)
            candidate.rerank_score = rerank_score
            candidate.score = (
                self.settings.reranker_weight * rerank_score
                + (1 - self.settings.reranker_weight) * candidate.score
            )
            candidate.rank_reason += f", reranker={rerank_score:.3f}"
        return sorted(candidates, key=lambda item: item.score, reverse=True)


def get_retriever() -> HybridRetriever:
    return HybridRetriever()
