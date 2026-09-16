"""Document splitting policy."""

from pathlib import Path
import logging

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings
from app.rag.wiki_parser import ParsedWikiPage


logger = logging.getLogger(__name__)


def split_documents(documents: list[Document], file_path: str) -> list[Document]:
    settings = get_settings()
    extension = Path(file_path).suffix.lower()
    # Excel 行在加载阶段已是完整语义单元，再切分会破坏商品与价格的对应关系。
    if extension in {".xlsx", ".xls"}:
        chunks = documents
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        chunks = splitter.split_documents(documents)

    # 切块序号写入 Chroma，HTML 等无页码文档可依靠它定位来源。
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
        chunk.metadata["chunk_total"] = len(chunks)
    logger.info(
        "documents split input_documents=%d chunks=%d extension=%s",
        len(documents),
        len(chunks),
        extension,
    )
    return chunks


def split_wiki_page(
    page: ParsedWikiPage,
    *,
    document_id: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    """Split a Wiki page without crossing semantic section boundaries."""

    settings = get_settings()
    effective_chunk_size = chunk_size or settings.chunk_size
    effective_chunk_overlap = (
        settings.chunk_overlap if chunk_overlap is None else chunk_overlap
    )
    if effective_chunk_size < 1:
        raise ValueError("chunk_size 必须大于 0")
    if effective_chunk_overlap < 0 or effective_chunk_overlap >= effective_chunk_size:
        raise ValueError("chunk_overlap 必须大于等于 0 且小于 chunk_size")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=effective_chunk_size,
        chunk_overlap=effective_chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", "",],
    )
    chunks: list[Document] = []

    for section_index, section in enumerate(page.sections):
        section_path = "/".join((page.title, *section.heading_path))
        section_parts = splitter.split_text(section.content)
        for section_chunk_index, part in enumerate(section_parts):
            metadata = {
                "type": "mediawiki",
                "source_type": "mediawiki",
                "source": page.title,
                "source_name": page.source_name,
                "title": page.title,
                "page_id": page.page_id,
                "revision_id": page.revision_id,
                "revision_timestamp": page.revision_timestamp,
                "section": section.title,
                "section_path": section_path,
                "section_type": section.section_type,
                "section_index": section_index,
                "section_chunk_index": section_chunk_index,
                "categories": "|".join(page.categories),
                "canonical_url": page.canonical_url,
                "content_sha256": page.content_sha256,
                "snapshot_path": page.snapshot_path,
            }
            if document_id:
                metadata["document_id"] = document_id
            chunks.append(
                Document(
                    page_content=(
                        f"页面：{page.title}\n"
                        f"章节：{' / '.join(section.heading_path)}\n\n"
                        f"{part}"
                    ),
                    metadata=metadata,
                )
            )

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
        chunk.metadata["chunk_total"] = len(chunks)

    logger.info(
        "Wiki page split page_id=%d revision_id=%d sections=%d chunks=%d",
        page.page_id,
        page.revision_id,
        len(page.sections),
        len(chunks),
    )
    return chunks
