import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import get_session_factory, init_db, reset_database_cache
from app.models.document import DocumentRecord, utc_now
from app.models.wiki import WikiPageRecord, WikiSource, WikiSyncRun
from app.rag.mediawiki import WikiPagePayload, WikiPageReference, WikiPageRevision
from app.rag.wiki_snapshot import WikiSnapshotStore
from app.commands.sync_wiki import build_parser
from app.services.wiki_sync_service import WikiSyncService


class FakeMediaWikiClient:
    def __init__(self, references, revisions, payloads):
        self.references = references
        self.revisions = revisions
        self.payloads = payloads
        self.fetch_page_calls: list[int] = []

    async def discover_pages(self, _root_categories):
        return self.references

    async def fetch_revisions(self, _page_ids):
        return self.revisions

    async def fetch_page(self, page_id):
        self.fetch_page_calls.append(page_id)
        return self.payloads[page_id]

    async def aclose(self):
        return None


@pytest.fixture
def wiki_sync_database(tmp_path, monkeypatch):
    database_path = tmp_path / "sync.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("MEDIAWIKI_API_URL", "https://example.test/api.php")
    monkeypatch.setenv("MEDIAWIKI_BASE_URL", "https://example.test")
    get_settings.cache_clear()
    reset_database_cache()
    init_db()
    yield tmp_path
    reset_database_cache()
    get_settings.cache_clear()


def revision(page_id: int, revision_id: int, title: str) -> WikiPageRevision:
    return WikiPageRevision(
        page_id=page_id,
        revision_id=revision_id,
        title=title,
        canonical_url=f"https://example.test/wiki/{title}",
        revision_timestamp="2026-09-13T00:00:00Z",
    )


def payload(page_id: int, revision_id: int, title: str) -> WikiPagePayload:
    metadata = revision(page_id, revision_id, title)
    return WikiPagePayload(
        page_id=metadata.page_id,
        revision_id=metadata.revision_id,
        title=metadata.title,
        canonical_url=metadata.canonical_url,
        revision_timestamp=metadata.revision_timestamp,
        wikitext=f"'''{title}''' 的原始内容",
        html=f"<p>{title} 的页面内容</p>",
    )


def add_local_page(session, source_id, page_id, revision_id, title, status="ready"):
    document = DocumentRecord(
        id=str(uuid4()),
        filename=title,
        content_type="text/html",
        size_bytes=100,
        status=status,
        chunk_count=2,
    )
    session.add(document)
    session.flush()
    page = WikiPageRecord(
        id=str(uuid4()),
        document_id=document.id,
        source_id=source_id,
        page_id=page_id,
        revision_id=revision_id,
        indexed_revision_id=revision_id,
        title=title,
        canonical_url=f"https://example.test/wiki/{title}",
        namespace=0,
        categories_json=json.dumps(["建筑"], ensure_ascii=False),
        content_sha256="a" * 64,
        snapshot_path=f"data/raw/wiki/{page_id}/{revision_id}.json",
        source_updated_at=utc_now(),
    )
    session.add(page)
    return document, page


def test_dry_run_is_strictly_read_only(wiki_sync_database):
    references = [WikiPageReference(1, "电解器", ("建筑",))]
    revisions = {1: revision(1, 10, "电解器")}
    client = FakeMediaWikiClient(references, revisions, {1: payload(1, 10, "电解器")})
    snapshot_root = wiki_sync_database / "snapshots"
    service = WikiSyncService(
        client=client,
        snapshot_store=WikiSnapshotStore(snapshot_root),
    )

    result = asyncio.run(service.run(dry_run=True))

    assert result.plan.counts() == {"create": 1, "update": 0, "unchanged": 0, "remove": 0}
    assert client.fetch_page_calls == []
    assert not snapshot_root.exists()
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(WikiSource)) == 0
        assert session.scalar(select(func.count()).select_from(WikiPageRecord)) == 0
        assert session.scalar(select(func.count()).select_from(WikiSyncRun)) == 0
        assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_cli_accepts_repeated_titles():
    args = build_parser().parse_args(
        ["--dry-run", "--title", "电解器", "--title", "哈奇"]
    )

    assert args.dry_run is True
    assert args.title == ["电解器", "哈奇"]


def test_partial_sync_does_not_remove_unselected_pages(wiki_sync_database):
    source_id = str(uuid4())
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
        session.add(source)
        unselected_document, _ = add_local_page(session, source_id, 2, 20, "气泵")
        session.commit()
        unselected_document_id = unselected_document.id

    references = [
        WikiPageReference(1, "哈奇", ("小动物",)),
        WikiPageReference(2, "气泵", ("建筑",)),
    ]
    revisions = {1: revision(1, 10, "哈奇")}
    client = FakeMediaWikiClient(
        references,
        revisions,
        {1: payload(1, 10, "哈奇")},
    )
    service = WikiSyncService(
        client=client,
        snapshot_store=WikiSnapshotStore(wiki_sync_database / "snapshots"),
    )

    result = asyncio.run(service.run(titles=[" 哈奇 ", "哈奇"]))

    assert result.scope == "partial"
    assert result.requested_titles == ("哈奇",)
    assert result.plan.counts() == {
        "create": 1,
        "update": 0,
        "unchanged": 0,
        "remove": 0,
    }
    assert client.fetch_page_calls == [1]
    with get_session_factory()() as session:
        source = session.get(WikiSource, source_id)
        sync_run = session.scalar(select(WikiSyncRun))
        assert session.get(DocumentRecord, unselected_document_id).status == "ready"
        assert source.last_synced_at is None
        assert sync_run.scope == "partial"
        assert json.loads(sync_run.requested_titles_json) == ["哈奇"]


def test_partial_dry_run_rejects_page_outside_allowed_scope(wiki_sync_database):
    client = FakeMediaWikiClient([], {}, {})
    service = WikiSyncService(
        client=client,
        snapshot_store=WikiSnapshotStore(wiki_sync_database / "snapshots"),
    )

    with pytest.raises(ValueError, match="不存在或不属于允许"):
        asyncio.run(service.run(dry_run=True, titles=["不存在的页面"]))

    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(WikiSource)) == 0
        assert session.scalar(select(func.count()).select_from(WikiSyncRun)) == 0


def test_sync_snapshots_only_new_and_updated_pages(wiki_sync_database):
    source_id = str(uuid4())
    with get_session_factory()() as session:
        session.add(
            WikiSource(
                id=source_id,
                name="缺氧 Wiki（中文）",
                api_url="https://example.test/api.php",
                base_url="https://example.test",
                language="zh",
                root_categories_json='["建筑", "小动物"]',
                excluded_category_keywords_json='["调试"]',
                status="active",
            )
        )
        unchanged_document, _ = add_local_page(session, source_id, 1, 10, "电解器")
        updated_document, _ = add_local_page(session, source_id, 2, 20, "气泵")
        removed_document, _ = add_local_page(session, source_id, 4, 40, "旧建筑")
        session.commit()
        unchanged_document_id = unchanged_document.id
        updated_document_id = updated_document.id
        removed_document_id = removed_document.id

    references = [
        WikiPageReference(1, "电解器", ("建筑",)),
        WikiPageReference(2, "气泵", ("建筑",)),
        WikiPageReference(3, "哈奇", ("小动物",)),
    ]
    revisions = {
        1: revision(1, 10, "电解器"),
        2: revision(2, 21, "气泵"),
        3: revision(3, 30, "哈奇"),
    }
    client = FakeMediaWikiClient(
        references,
        revisions,
        {
            2: payload(2, 21, "气泵"),
            3: payload(3, 30, "哈奇"),
        },
    )
    snapshot_root = wiki_sync_database / "snapshots"
    service = WikiSyncService(
        client=client,
        snapshot_store=WikiSnapshotStore(snapshot_root),
    )

    result = asyncio.run(service.run())

    assert result.plan.counts() == {"create": 1, "update": 1, "unchanged": 1, "remove": 1}
    assert result.failed_count == 0
    assert client.fetch_page_calls == [3, 2]
    assert (snapshot_root / "2" / "21.json").exists()
    assert (snapshot_root / "3" / "30.json").exists()

    with get_session_factory()() as session:
        updated_page = session.scalar(select(WikiPageRecord).where(WikiPageRecord.page_id == 2))
        created_page = session.scalar(select(WikiPageRecord).where(WikiPageRecord.page_id == 3))
        source = session.get(WikiSource, source_id)
        sync_run = session.scalar(select(WikiSyncRun))
        assert session.get(DocumentRecord, unchanged_document_id).status == "ready"
        assert session.get(DocumentRecord, updated_document_id).status == "pending_index"
        assert session.get(DocumentRecord, removed_document_id).status == "source_removed"
        assert updated_page.revision_id == 21
        assert updated_page.indexed_revision_id == 20
        assert created_page.indexed_revision_id is None
        assert source.last_synced_at is not None
        assert sync_run.scope == "full"
        assert sync_run.requested_titles_json is None
        assert sync_run.status == "completed"
        assert sync_run.created_count == 1
        assert sync_run.updated_count == 1
        assert sync_run.unchanged_count == 1
        assert sync_run.removed_count == 1
