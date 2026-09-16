import json
from uuid import uuid4

import pytest

from app.commands.index_wiki import build_parser
from app.core.config import get_settings
from app.core.database import get_session_factory, init_db, reset_database_cache
from app.models.document import DocumentRecord, utc_now
from app.models.wiki import WikiPageRecord, WikiSource
from app.services import wiki_index_service
from app.services.wiki_index_service import WikiIndexService


@pytest.fixture
def wiki_index_database(tmp_path, monkeypatch):
    database_path = tmp_path / "index.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    reset_database_cache()
    init_db()
    yield tmp_path
    reset_database_cache()
    get_settings.cache_clear()


def write_snapshot(tmp_path, *, page_id=1, revision_id=10, title="电解器"):
    path = tmp_path / f"{page_id}-{revision_id}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": {"name": "缺氧 Wiki（中文）"},
                "page": {
                    "page_id": page_id,
                    "revision_id": revision_id,
                    "title": title,
                    "canonical_url": f"https://example.test/wiki/{title}",
                    "revision_timestamp": "2026-09-16T00:00:00Z",
                    "categories": ["氧气建筑"],
                },
                "content_sha256": "a" * 64,
                "html": (
                    '<div class="mw-parser-output">'
                    f"<p>{title}的摘要内容。</p>"
                    "<h2>机制</h2><p>每秒消耗水并产生氧气。</p>"
                    "</div>"
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def add_wiki_page(
    snapshot_path,
    *,
    stored_snapshot_path=None,
    page_id=1,
    revision_id=10,
    indexed_revision_id=None,
    title="电解器",
    status="pending_index",
    chunk_count=0,
):
    source_id = str(uuid4())
    document_id = str(uuid4())
    page_record_id = str(uuid4())
    with get_session_factory()() as session:
        source = WikiSource(
            id=source_id,
            name="缺氧 Wiki（中文）",
            api_url="https://example.test/api.php",
            base_url="https://example.test",
            language="zh",
            root_categories_json='["建筑", "小动物"]',
            excluded_category_keywords_json='["调试"]',
            status="active",
        )
        document = DocumentRecord(
            id=document_id,
            filename=title,
            content_type="text/html",
            size_bytes=snapshot_path.stat().st_size,
            status=status,
            chunk_count=chunk_count,
        )
        session.add_all([source, document])
        session.flush()
        session.add(
            WikiPageRecord(
                id=page_record_id,
                document_id=document_id,
                source_id=source_id,
                page_id=page_id,
                revision_id=revision_id,
                indexed_revision_id=indexed_revision_id,
                namespace=0,
                title=title,
                canonical_url=f"https://example.test/wiki/{title}",
                categories_json='["氧气建筑"]',
                content_sha256="a" * 64,
                snapshot_path=str(stored_snapshot_path or snapshot_path),
                source_updated_at=utc_now(),
            )
        )
        session.commit()
    return document_id, page_record_id


def test_wiki_index_service_dry_run_then_index_and_skip(
    wiki_index_database, monkeypatch
):
    snapshot_path = write_snapshot(wiki_index_database)
    monkeypatch.setattr(wiki_index_service, "PROJECT_ROOT", wiki_index_database)
    document_id, page_record_id = add_wiki_page(
        snapshot_path,
        stored_snapshot_path=snapshot_path.name,
    )
    calls = []

    def fake_replace(chunks, **kwargs):
        calls.append((chunks, kwargs))
        return len(chunks), 0

    monkeypatch.setattr(
        wiki_index_service,
        "replace_wiki_revision_chunks",
        fake_replace,
    )
    service = WikiIndexService()

    dry_run = service.run(dry_run=True, titles=[" 电解器 ", "电解器"])

    assert len(dry_run.planned_items) == 1
    assert calls == []
    with get_session_factory()() as session:
        assert session.get(DocumentRecord, document_id).status == "pending_index"

    result = service.run(titles=["电解器"])

    assert result.indexed_count == 1
    assert result.failed_count == 0
    assert result.chunk_count == 2
    assert len(calls) == 1
    chunks, kwargs = calls[0]
    assert kwargs == {
        "page_id": 1,
        "revision_id": 10,
        "previous_revision_id": None,
    }
    assert all(chunk.metadata["document_id"] == document_id for chunk in chunks)
    assert all(
        chunk.metadata["snapshot_path"] == snapshot_path.name
        for chunk in chunks
    )
    assert {chunk.metadata["section"] for chunk in chunks} == {"摘要", "机制"}
    with get_session_factory()() as session:
        document = session.get(DocumentRecord, document_id)
        page = session.get(WikiPageRecord, page_record_id)
        assert document.status == "ready"
        assert document.chunk_count == 2
        assert document.error_message is None
        assert page.indexed_revision_id == 10

    second_result = service.run(titles=["电解器"])

    assert second_result.indexed_count == 0
    assert second_result.skipped_count == 1
    assert len(calls) == 1


def test_wiki_index_service_preserves_indexed_revision_on_failure(
    wiki_index_database, monkeypatch
):
    snapshot_path = write_snapshot(wiki_index_database)
    document_id, page_record_id = add_wiki_page(
        snapshot_path,
        indexed_revision_id=9,
        chunk_count=4,
    )

    def fail_replace(_chunks, **_kwargs):
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(
        wiki_index_service,
        "replace_wiki_revision_chunks",
        fail_replace,
    )

    result = WikiIndexService().run()

    assert result.indexed_count == 0
    assert result.failed_count == 1
    assert "embedding failed" in result.failures[0]
    with get_session_factory()() as session:
        document = session.get(DocumentRecord, document_id)
        page = session.get(WikiPageRecord, page_record_id)
        assert document.status == "index_failed"
        assert document.chunk_count == 4
        assert "embedding failed" in document.error_message
        assert page.indexed_revision_id == 9


def test_index_wiki_cli_accepts_titles_and_limit():
    args = build_parser().parse_args(
        ["--dry-run", "--verbose", "--limit", "3", "--title", "电解器"]
    )

    assert args.dry_run is True
    assert args.verbose is True
    assert args.limit == 3
    assert args.title == ["电解器"]
