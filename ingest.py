"""Compatibility wrapper for the first-stage Streamlit entrypoint."""

from app.rag.embeddings import get_embeddings
from app.rag.ingestion import ingest
from app.rag.loaders import load_excel, load_file, load_html

__all__ = ["get_embeddings", "ingest", "load_excel", "load_file", "load_html"]
