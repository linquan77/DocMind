import math
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

from config import *


def get_embeddings():
    os.environ.setdefault("HF_HOME", MODEL_CACHE_PATH)
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_PATH)
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        cache_folder=MODEL_CACHE_PATH,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


@dataclass
class RetrievalResult:
    doc: Document
    score: float
    vector_score: float = 0.0
    bm25_score: float = 0.0
    rerank_score: Optional[float] = None
    rank_reason: str = ""


def _tokenize(text: str) -> List[str]:
    """A small tokenizer that works for Chinese text without extra packages."""
    text = (text or "").lower()
    english_or_number = re.findall(r"[a-z0-9]+", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    chinese_bigrams = [
        "".join(chinese_chars[i : i + 2])
        for i in range(len(chinese_chars) - 1)
    ]
    return english_or_number + chinese_chars + chinese_bigrams


def _metadata_match(metadata: Dict[str, Any], metadata_filter: Optional[Dict[str, Any]]) -> bool:
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


def _build_chroma_filter(metadata_filter: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not metadata_filter:
        return None
    if len(metadata_filter) == 1:
        return metadata_filter
    return {"$and": [{key: value} for key, value in metadata_filter.items()]}


def _normalize_scores(items: Iterable[Tuple[str, float]]) -> Dict[str, float]:
    items = list(items)
    if not items:
        return {}
    values = [score for _, score in items]
    min_score = min(values)
    max_score = max(values)
    if math.isclose(max_score, min_score):
        return {key: 1.0 for key, _ in items}
    return {key: (score - min_score) / (max_score - min_score) for key, score in items}


class SimpleBM25:
    def __init__(self, tokenized_documents: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = tokenized_documents
        self.k1 = k1
        self.b = b
        self.avgdl = sum(len(doc) for doc in self.docs) / max(len(self.docs), 1)
        self.doc_freq: Dict[str, int] = {}
        for doc in self.docs:
            for token in set(doc):
                self.doc_freq[token] = self.doc_freq.get(token, 0) + 1

    def score(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0
        freqs: Dict[str, int] = {}
        for token in doc_tokens:
            freqs[token] = freqs.get(token, 0) + 1

        score = 0.0
        doc_len = len(doc_tokens)
        total_docs = max(len(self.docs), 1)
        for token in query_tokens:
            tf = freqs.get(token, 0)
            if tf == 0:
                continue
            df = self.doc_freq.get(token, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            denom = tf + self.k1 * (1 - self.b + self.b * doc_len / max(self.avgdl, 1))
            score += idf * (tf * (self.k1 + 1) / denom)
        return score


class HybridRetriever:
    def __init__(self):
        self.embeddings = get_embeddings()
        self.vectorstore = Chroma(
            persist_directory=CHROMA_DB_PATH,
            embedding_function=self.embeddings,
        )
        self._reranker = None
        self._reranker_failed = False

    def retrieve(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, Any]] = None,
        top_k: int = TOP_K,
    ) -> List[RetrievalResult]:
        all_docs = self._load_all_documents(metadata_filter)
        if not all_docs:
            return []

        vector_hits = self._vector_search(query, metadata_filter)
        bm25_hits = self._bm25_search(query, all_docs)
        fused = self._fuse_results(vector_hits, bm25_hits, all_docs)
        reranked = self._rerank(query, fused[:RERANKER_CANDIDATE_K])
        filtered = [
            item for item in reranked
            if item.score >= RERANKER_SCORE_THRESHOLD
        ]
        return filtered[:top_k]

    def _load_all_documents(self, metadata_filter: Optional[Dict[str, Any]]) -> Dict[str, Document]:
        result = self.vectorstore.get(include=["documents", "metadatas"])
        docs: Dict[str, Document] = {}
        for doc_id, text, metadata in zip(result.get("ids", []), result.get("documents", []), result.get("metadatas", [])):
            metadata = metadata or {}
            if _metadata_match(metadata, metadata_filter):
                docs[doc_id] = Document(page_content=text or "", metadata={**metadata, "_chunk_id": doc_id})
        return docs

    def _vector_search(self, query: str, metadata_filter: Optional[Dict[str, Any]]) -> List[Tuple[str, float]]:
        try:
            hits = self.vectorstore.similarity_search_with_score(
                query,
                k=VECTOR_TOP_K,
                filter=_build_chroma_filter(metadata_filter),
            )
        except TypeError:
            hits = self.vectorstore.similarity_search_with_score(query, k=VECTOR_TOP_K)

        scored = []
        for doc, distance in hits:
            chunk_id = doc.metadata.get("_chunk_id") or self._find_chunk_id(doc)
            if chunk_id:
                similarity = 1 / (1 + max(float(distance), 0.0))
                scored.append((chunk_id, similarity))
        return scored

    def _find_chunk_id(self, doc: Document) -> Optional[str]:
        result = self.vectorstore.get(
            where={"source": doc.metadata.get("source", "")},
            include=["documents", "metadatas"],
        )
        for doc_id, text in zip(result.get("ids", []), result.get("documents", [])):
            if text == doc.page_content:
                return doc_id
        return None

    def _bm25_search(self, query: str, docs: Dict[str, Document]) -> List[Tuple[str, float]]:
        doc_ids = list(docs.keys())
        tokenized_docs = [_tokenize(docs[doc_id].page_content) for doc_id in doc_ids]
        bm25 = SimpleBM25(tokenized_docs)
        query_tokens = _tokenize(query)
        scores = [
            (doc_id, bm25.score(query_tokens, tokens))
            for doc_id, tokens in zip(doc_ids, tokenized_docs)
        ]
        return sorted(scores, key=lambda item: item[1], reverse=True)[:BM25_TOP_K]

    def _fuse_results(
        self,
        vector_hits: List[Tuple[str, float]],
        bm25_hits: List[Tuple[str, float]],
        docs: Dict[str, Document],
    ) -> List[RetrievalResult]:
        vector_scores = _normalize_scores(vector_hits)
        bm25_scores = _normalize_scores(bm25_hits)
        candidate_ids = set(vector_scores) | set(bm25_scores)
        results = []
        for doc_id in candidate_ids:
            vector_score = vector_scores.get(doc_id, 0.0)
            bm25_score = bm25_scores.get(doc_id, 0.0)
            combined = VECTOR_WEIGHT * vector_score + BM25_WEIGHT * bm25_score
            results.append(
                RetrievalResult(
                    doc=docs[doc_id],
                    score=combined,
                    vector_score=vector_score,
                    bm25_score=bm25_score,
                    rank_reason=f"vector={vector_score:.3f}, bm25={bm25_score:.3f}",
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)

    def _rerank(self, query: str, candidates: List[RetrievalResult]) -> List[RetrievalResult]:
        if not ENABLE_RERANKER or not candidates:
            return candidates
        reranker = self._load_reranker()
        if reranker is None:
            return candidates

        pairs = [(query, item.doc.page_content) for item in candidates]
        raw_scores = reranker.predict(pairs)
        normalized = _normalize_scores([
            (str(index), float(score))
            for index, score in enumerate(raw_scores)
        ])
        for index, item in enumerate(candidates):
            rerank_score = normalized.get(str(index), 0.0)
            item.rerank_score = rerank_score
            item.score = RERANKER_WEIGHT * rerank_score + (1 - RERANKER_WEIGHT) * item.score
            item.rank_reason += f", reranker={rerank_score:.3f}"
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _load_reranker(self):
        if self._reranker or self._reranker_failed:
            return self._reranker
        try:
            from sentence_transformers import CrossEncoder

            os.environ.setdefault("HF_HOME", MODEL_CACHE_PATH)
            os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_PATH)
            self._reranker = CrossEncoder(RERANKER_MODEL, device="cpu", cache_folder=MODEL_CACHE_PATH)
        except Exception:
            self._reranker_failed = True
            self._reranker = None
        return self._reranker


def get_retriever():
    return HybridRetriever()
