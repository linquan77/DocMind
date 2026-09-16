from fastapi.testclient import TestClient
import pytest

from app.api import documents as documents_api
from app.core.config import get_settings
from app.core.database import init_db, reset_database_cache
from app.main import app
from app.services.document_service import update_document
from app.services.document_service import create_document_record, delete_document_by_id
from app.rag import vectorstore


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    database_path = tmp_path / "documents.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    reset_database_cache()
    init_db()
    yield
    reset_database_cache()
    get_settings.cache_clear()


def test_upload_and_list_documents(isolated_database, monkeypatch):
    def fake_ingest(document, _temp_path):
        return update_document(document.id, status="ready", chunk_count=2)

    monkeypatch.setattr(documents_api, "ingest_document", fake_ingest)

    with TestClient(app) as client:
        response = client.post(
            "/documents",
            files={"file": ("knowledge.html", b"<h1>knowledge</h1>", "text/html")},
        )

        assert response.status_code == 201
        assert response.json()["status"] == "ready"
        assert response.json()["chunk_count"] == 2

        listing = client.get("/documents")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assert listing.json()["items"][0]["filename"] == "knowledge.html"


def test_upload_rejects_unsupported_file(isolated_database):
    with TestClient(app) as client:
        response = client.post(
            "/documents",
            files={"file": ("notes.txt", b"not supported", "text/plain")},
        )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_document_type"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]


def test_delete_removes_metadata_and_chroma_chunks(isolated_database, monkeypatch):
    document = create_document_record(
        filename="to-delete.pdf",
        content_type="application/pdf",
        size_bytes=123,
    )
    monkeypatch.setattr(vectorstore, "delete_document_chunks", lambda _document_id: 3)

    # document_service imported the function directly, so patch that service
    # reference as well as the module-level helper.
    monkeypatch.setattr(
        "app.services.document_service.delete_document_chunks",
        lambda _document_id: 3,
    )
    result = delete_document_by_id(document.id)

    assert result.deleted_chunks == 3
    with TestClient(app) as client:
        listing = client.get("/documents")
    assert listing.json()["total"] == 0


def test_delete_returns_404_for_missing_document(isolated_database):
    with TestClient(app) as client:
        response = client.delete("/documents/missing-document-id")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"
