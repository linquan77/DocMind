"""Document splitting policy."""

from pathlib import Path
import logging

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings


logger = logging.getLogger(__name__)


def split_documents(documents: list[Document], file_path: str) -> list[Document]:
    settings = get_settings()
    extension = Path(file_path).suffix.lower()
    if extension in {".xlsx", ".xls"}:
        chunks = documents
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        chunks = splitter.split_documents(documents)

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
