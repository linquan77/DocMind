"""Compatibility wrapper for the first-stage Streamlit entrypoint."""

# 真正的解析、切块和向量写入已迁移到 app.rag，这里只保证历史 import 不失效。

from app.rag.embeddings import get_embeddings
from app.rag.ingestion import ingest
from app.rag.loaders import load_excel, load_file, load_html

__all__ = ["get_embeddings", "ingest", "load_excel", "load_file", "load_html"]
