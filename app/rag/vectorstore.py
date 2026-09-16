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
