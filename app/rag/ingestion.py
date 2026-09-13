"""Document ingestion pipeline."""

from collections.abc import Callable
import logging
import time

from app.rag.loaders import load_file
from app.rag.splitter import split_documents
from app.rag.vectorstore import add_document_chunks, document_chunks_exist


ProgressCallback = Callable[[float, str], None]
logger = logging.getLogger(__name__)


def ingest(
    file_path: str,
    original_name: str | None = None,
    progress_callback: ProgressCallback | None = None,
    document_id: str | None = None,
) -> int:
    started = time.perf_counter()
    logger.info("document ingestion started source=%s", original_name or file_path)
    if progress_callback:
        progress_callback(0.1, "加载文件...")
    documents = load_file(file_path)
    logger.info("document loaded units=%d", len(documents))

    source = original_name or file_path
    for document in documents:
        document.metadata["source"] = source
        if document_id:
            document.metadata["document_id"] = document_id

    if progress_callback:
        progress_callback(0.3, "分割内容...")
    chunks = split_documents(documents, file_path)
    logger.info("document split chunks=%d", len(chunks))

    if progress_callback:
        progress_callback(0.5, "检查重复...")
    if document_chunks_exist(document_id=document_id, source=source):
        if progress_callback:
            progress_callback(1.0, "已跳过")
        logger.info("document ingestion skipped reason=duplicate source=%s", source)
        return 0

    if progress_callback:
        progress_callback(0.7, "写入数据库...")
    add_document_chunks(chunks)
    if progress_callback:
        progress_callback(1.0, "完成！")
    logger.info(
        "document ingestion completed chunks=%d latency_ms=%d",
        len(chunks),
        int((time.perf_counter() - started) * 1000),
    )
    return len(chunks)
