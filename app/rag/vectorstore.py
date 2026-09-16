"""Low-level Chroma operations used by application services."""

import chromadb
import logging
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

from app.core.config import get_settings
from app.rag.embeddings import get_embeddings


logger = logging.getLogger(__name__)


def get_chroma_client():
    """Create a client without loading the embedding model."""

    # 删除和元数据查询不需要计算向量，原生客户端可避免加载 Embedding 模型。
    return chromadb.PersistentClient(path=get_settings().chroma_db_path)


def get_vectorstore() -> Chroma:
    # 只有相似度检索和新增切块需要绑定 Embedding 函数。
    return Chroma(
        persist_directory=get_settings().chroma_db_path,
        embedding_function=get_embeddings(),
    )


def document_chunks_exist(*, document_id: str | None, source: str) -> bool:
    vectorstore = get_vectorstore()
    where = {"document_id": document_id} if document_id else {"source": source}
    result = vectorstore.get(where=where)
    return bool(result.get("ids"))


def add_document_chunks(chunks: list[Document]) -> None:
    if chunks:
        get_vectorstore().add_documents(chunks)
        logger.info("Chroma chunks added count=%d", len(chunks))


def build_wiki_chunk_ids(
    *, page_id: int, revision_id: int, chunk_count: int
) -> list[str]:
    """Build deterministic IDs so one Wiki revision can be retried safely."""

    return [
        f"wiki:{page_id}:{revision_id}:{chunk_index}"
        for chunk_index in range(chunk_count)
    ]


def _wiki_revision_filter(page_id: int, revision_id: int) -> dict:
    return {
        "$and": [
            {"source_type": "mediawiki"},
            {"page_id": page_id},
            {"revision_id": revision_id},
        ]
    }


def count_wiki_revision_chunks(page_id: int, revision_id: int) -> int:
    """Count chunks for one exact Wiki revision across Chroma collections."""

    client = get_chroma_client()
    count = 0
    where = _wiki_revision_filter(page_id, revision_id)
    for collection in client.list_collections():
        result = collection.get(where=where, include=["metadatas"])
        count += len(result.get("ids", []))
    return count


def delete_wiki_revision_chunks(page_id: int, revision_id: int) -> int:
    """Delete only one Wiki revision, leaving older/newer revisions untouched."""

    client = get_chroma_client()
    deleted_count = 0
    where = _wiki_revision_filter(page_id, revision_id)
    for collection in client.list_collections():
        result = collection.get(where=where, include=["metadatas"])
        ids = result.get("ids", [])
        if ids:
            collection.delete(ids=ids)
            deleted_count += len(ids)
    logger.info(
        "Wiki revision chunks deleted page_id=%d revision_id=%d count=%d",
        page_id,
        revision_id,
        deleted_count,
    )
    return deleted_count


def add_wiki_revision_chunks(
    chunks: list[Document], *, page_id: int, revision_id: int
) -> int:
    """Add one Wiki revision with deterministic IDs and verify its count."""

    if not chunks:
        raise ValueError("Wiki 页面没有可写入的切块")
    ids = build_wiki_chunk_ids(
        page_id=page_id,
        revision_id=revision_id,
        chunk_count=len(chunks),
    )
    inserted_ids = get_vectorstore().add_documents(chunks, ids=ids)
    if len(inserted_ids) != len(chunks):
        raise RuntimeError(
            f"Chroma 返回的切块数量不一致: expected={len(chunks)}, actual={len(inserted_ids)}"
        )
    actual_count = count_wiki_revision_chunks(page_id, revision_id)
    if actual_count != len(chunks):
        raise RuntimeError(
            f"Chroma 写入校验失败: expected={len(chunks)}, actual={actual_count}"
        )
    logger.info(
        "Wiki revision chunks added page_id=%d revision_id=%d count=%d",
        page_id,
        revision_id,
        actual_count,
    )
    return actual_count


def replace_wiki_revision_chunks(
    chunks: list[Document],
    *,
    page_id: int,
    revision_id: int,
    previous_revision_id: int | None,
) -> tuple[int, int]:
    """Write and verify a new revision before removing the previously indexed one.

    A stale copy of the target revision is cleared first to make retries
    idempotent. The previous good revision remains available until the new
    revision has been fully embedded and verified.
    """

    if previous_revision_id == revision_id:
        raise ValueError("新旧 Wiki revision_id 相同，无需替换")

    # 清理上次失败可能遗留的同版本切块，但暂时保留旧的可用版本。
    delete_wiki_revision_chunks(page_id, revision_id)
    try:
        added_count = add_wiki_revision_chunks(
            chunks,
            page_id=page_id,
            revision_id=revision_id,
        )
    except Exception:
        # 写入失败时清理目标版本，避免不完整向量混入检索。
        delete_wiki_revision_chunks(page_id, revision_id)
        raise

    removed_count = 0
    if previous_revision_id is not None:
        try:
            removed_count = delete_wiki_revision_chunks(page_id, previous_revision_id)
        except Exception:
            # 旧版本删除失败时撤回新版本，避免两个修订同时参与检索。
            delete_wiki_revision_chunks(page_id, revision_id)
            raise
    return added_count, removed_count


def delete_document_chunks(document_id: str) -> int:
    """Delete all Chroma chunks belonging to one API document.

    API-managed chunks carry ``document_id`` in their metadata. Iterating over
    collections keeps this helper compatible with the existing Chroma layout,
    which uses the default LangChain collection name.
    """

    client = get_chroma_client()
    # 遍历集合可兼容后续按租户或知识库拆分 Collection 的部署方式。
    deleted_count = 0
    for collection in client.list_collections():
        result = collection.get(where={"document_id": document_id}, include=["metadatas"])
        ids = result.get("ids", [])
        if ids:
            collection.delete(ids=ids)
            deleted_count += len(ids)
    logger.info("Chroma chunks deleted document_id=%s count=%d", document_id, deleted_count)
    return deleted_count
