"""Document upload and catalog endpoints."""

import asyncio
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, Query, UploadFile, status

from app.core.exceptions import AppError
from app.core.logging import trace_id_context
from app.schemas.documents import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentResponse,
)
from app.services.document_service import (
    create_document_record,
    delete_document_by_id,
    document_filename_exists,
    ingest_document,
    list_document_records,
    update_document,
)


router = APIRouter(prefix="/documents", tags=["documents"])
# 第一版只允许可控的本地文件类型，避免把任意上传内容交给解析器。
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".html", ".htm"}


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED, summary="上传并入库文档")
async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
    # Path.name 会去掉客户端可能携带的目录，防止文件名影响服务端临时路径。
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in SUPPORTED_EXTENSIONS:
        raise AppError(
            "仅支持 PDF、DOCX、XLSX、XLS、HTML 和 HTM 文件",
            status_code=415,
            code="unsupported_document_type",
        )

    # SQLite 和后续 RAG 入库都是同步操作，放入工作线程，避免阻塞 FastAPI 事件循环。
    if await asyncio.to_thread(document_filename_exists, filename):
        raise AppError(
            f"文档已存在：{filename}",
            status_code=409,
            code="document_already_exists",
        )

    content = await file.read()
    if not content:
        raise AppError("上传文件不能为空", status_code=400, code="empty_document")

    document = await asyncio.to_thread(
        create_document_record,
        filename=filename,
        content_type=file.content_type,
        size_bytes=len(content),
    )

    temp_path: Path | None = None
    try:
        # 保留扩展名，文档加载器依赖后缀判断具体解析方式。
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)
        await asyncio.to_thread(temp_path.write_bytes, content)
        document = await asyncio.to_thread(ingest_document, document, temp_path)
        return DocumentResponse.model_validate(document)
    except Exception as exc:
        await asyncio.to_thread(
            update_document,
            document.id,
            status="failed",
            error_message=str(exc),
        )
        if isinstance(exc, AppError):
            raise
        raise AppError(
            "文档解析或入库失败",
            status_code=422,
            code="document_ingestion_failed",
        ) from exc
    finally:
        # 无论解析成功还是失败都清理临时文件，原始文件不会长期保存在本机。
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        await file.close()


@router.get("", response_model=DocumentListResponse, summary="获取文档列表")
async def get_documents(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> DocumentListResponse:
    items, total = await asyncio.to_thread(list_document_records, offset=offset, limit=limit)
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="删除文档及其向量切块",
)
async def delete_document(document_id: str) -> DocumentDeleteResponse:
    # 删除顺序和失败补偿由 Service 层负责，API 层只转换请求与响应。
    result = await asyncio.to_thread(delete_document_by_id, document_id)
    return DocumentDeleteResponse(
        id=result.id,
        filename=result.filename,
        deleted_chunks=result.deleted_chunks,
        message="文档及其向量切块已删除",
        trace_id=trace_id_context.get(),
    )
