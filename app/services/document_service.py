"""Document metadata and ingestion service."""

from dataclasses import dataclass
import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.core.exceptions import AppError
from app.models.document import DocumentRecord
from app.rag.vectorstore import delete_document_chunks
from app.rag.ingestion import ingest


logger = logging.getLogger(__name__)


def create_document_record(
    *, filename: str, content_type: str | None, size_bytes: int
) -> DocumentRecord:
    # 先登记 processing 状态，使上传后的处理进度可查询；向量写入成功后再改为 ready。
    document = DocumentRecord(
        id=str(uuid4()),
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        status="processing",
    )
    with get_session_factory()() as session:
        session.add(document)
        session.commit()
        session.refresh(document)
        return document


def document_filename_exists(filename: str) -> bool:
    with get_session_factory()() as session:
        statement = select(DocumentRecord.id).where(DocumentRecord.filename == filename).limit(1)
        return session.execute(statement).scalar_one_or_none() is not None


def update_document(
    document_id: str,
    *,
    status: str,
    chunk_count: int = 0,
    error_message: str | None = None,
) -> DocumentRecord | None:
    with get_session_factory()() as session:
        document = session.get(DocumentRecord, document_id)
        if document is None:
            return None
        document.status = status
        document.chunk_count = chunk_count
        document.error_message = error_message
        session.commit()
        session.refresh(document)
        return document


def list_document_records(*, offset: int, limit: int) -> tuple[list[DocumentRecord], int]:
    with get_session_factory()() as session:
        total = session.scalar(select(func.count()).select_from(DocumentRecord)) or 0
        statement = (
            select(DocumentRecord)
            .order_by(DocumentRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list(session.scalars(statement).all())
        return items, int(total)


@dataclass(frozen=True)
class DocumentDeleteResult:
    id: str
    filename: str
    deleted_chunks: int


def delete_document_by_id(document_id: str) -> DocumentDeleteResult:
    """Delete Chroma chunks first, then remove the SQLite metadata record."""

    with get_session_factory()() as session:
        document = session.get(DocumentRecord, document_id)
        if document is None:
            raise AppError(
                "文档不存在",
                status_code=404,
                code="document_not_found",
            )
        filename = document.filename
        # 先标记 deleting，避免删除期间仍被当作可用文档展示或检索。
        document.status = "deleting"
        document.error_message = None
        session.commit()

    try:
        # 先删除 Chroma 切块；若失败，SQLite 元数据仍在，便于恢复和重试。
        deleted_chunks = delete_document_chunks(document_id)
    except Exception as exc:
        # SQLite 与 Chroma 无法共享事务，因此通过恢复状态做补偿。
        logger.exception("failed to delete Chroma chunks for document %s", document_id)
        update_document(
            document_id,
            status="ready",
            chunk_count=document.chunk_count,
            error_message="向量数据删除失败，请稍后重试",
        )
        raise AppError(
            "文档向量数据删除失败",
            status_code=503,
            code="vector_store_delete_failed",
        ) from exc

    with get_session_factory()() as session:
        # 只有向量数据删除成功后才移除元数据，避免留下无法定位的孤儿向量。
        document = session.get(DocumentRecord, document_id)
        if document is not None:
            session.delete(document)
            session.commit()

    return DocumentDeleteResult(
        id=document_id,
        filename=filename,
        deleted_chunks=deleted_chunks,
    )


def ingest_document(document: DocumentRecord, temp_path: Path) -> DocumentRecord:
    """Run the existing synchronous RAG ingestion outside the event loop."""

    # 解析、模型推理和向量写入都是同步耗时操作，API 层会在线程池中调用本函数。
    chunk_count = ingest(
        str(temp_path),
        original_name=document.filename,
        document_id=document.id,
    )
    updated = update_document(document.id, status="ready", chunk_count=chunk_count)
    if updated is None:
        raise RuntimeError(f"Document {document.id} disappeared during ingestion")
    return updated
