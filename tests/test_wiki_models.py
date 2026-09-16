import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import get_session_factory, init_db, reset_database_cache
from app.models.document import DocumentRecord, utc_now
from app.models.wiki import WikiPageRecord, WikiSource, WikiSyncRun


@pytest.fixture
def wiki_database(tmp_path, monkeypatch):
    database_path = tmp_path / "wiki.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    reset_database_cache()
    init_db()
    yield
    reset_database_cache()
    get_settings.cache_clear()


def test_wiki_models_store_revision_metadata_and_enforce_cascade(wiki_database):
    source_id = str(uuid4())
    document_id = str(uuid4())
    page_record_id = str(uuid4())
    sync_run_id = str(uuid4())

    with get_session_factory()() as session:
        session.add(
            WikiSource(
                id=source_id,
                name="缺氧 Wiki（中文）",
                api_url="https://oxygennotincluded.wiki.gg/zh/api.php",
                base_url="https://oxygennotincluded.wiki.gg/zh",
                language="zh",
                root_categories_json=json.dumps(["建筑", "小动物"], ensure_ascii=False),
                excluded_category_keywords_json=json.dumps(["调试", "未实装"], ensure_ascii=False),
                license_name="CC BY-NC-SA 4.0",
                license_url="https://creativecommons.org/licenses/by-nc-sa/4.0/",
                status="active",
            )
        )
        session.add(
            DocumentRecord(
                id=document_id,
                filename="电解器",
                content_type="text/html",
                size_bytes=1024,
                status="ready",
                chunk_count=3,
            )
        )
        session.flush()
        session.add(
            WikiPageRecord(
                id=page_record_id,
                document_id=document_id,
                source_id=source_id,
                page_id=123,
                revision_id=456,
                title="电解器",
                canonical_url="https://oxygennotincluded.wiki.gg/zh/wiki/电解器",
                namespace=0,
                categories_json=json.dumps(["建筑"], ensure_ascii=False),
                content_sha256="a" * 64,
                snapshot_path="data/raw/wiki/123/456.json",
                source_updated_at=utc_now(),
            )
        )
        session.add(WikiSyncRun(id=sync_run_id, source_id=source_id, status="running"))
        session.commit()

    with get_session_factory()() as session:
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
        page = session.scalar(select(WikiPageRecord).where(WikiPageRecord.page_id == 123))
        assert page is not None
        assert page.revision_id == 456
        session.delete(session.get(DocumentRecord, document_id))
        session.commit()
        session.expunge_all()
        assert session.scalar(
            select(WikiPageRecord).where(WikiPageRecord.id == page_record_id)
        ) is None
        assert session.get(WikiSource, source_id) is not None
        assert session.get(WikiSyncRun, sync_run_id) is not None
