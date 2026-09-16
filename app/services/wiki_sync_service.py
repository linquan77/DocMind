"""Application service for incremental MediaWiki snapshot synchronization."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.document import DocumentRecord, utc_now
from app.models.wiki import WikiPageRecord, WikiSource, WikiSyncRun
from app.rag.mediawiki import (
    MediaWikiAPIError,
    MediaWikiClient,
    WikiPageReference,
    WikiPagePayload,
    WikiPageRevision,
)
from app.rag.wiki_snapshot import SnapshotRecord, WikiSnapshotStore


logger = logging.getLogger(__name__)
SOURCE_NAME = "缺氧 Wiki（中文）"
LICENSE_NAME = "CC BY-NC-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans"


class SyncAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    REMOVE = "remove"


@dataclass(frozen=True)
class LocalWikiPageState:
    page_record_id: str
    document_id: str
    page_id: int
    revision_id: int
    title: str
    canonical_url: str
    categories: tuple[str, ...]
    document_status: str


@dataclass(frozen=True)
class SyncPlanItem:
    action: SyncAction
    page_id: int
    title: str
    remote_revision_id: int | None
    local_revision_id: int | None
    categories: tuple[str, ...]
    document_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "page_id": self.page_id,
            "title": self.title,
            "remote_revision_id": self.remote_revision_id,
            "local_revision_id": self.local_revision_id,
            "categories": list(self.categories),
            "document_id": self.document_id,
        }


@dataclass(frozen=True)
class WikiSyncPlan:
    items: tuple[SyncPlanItem, ...]

    def for_action(self, action: SyncAction) -> list[SyncPlanItem]:
        return [item for item in self.items if item.action == action]

    def counts(self) -> dict[str, int]:
        return {action.value: len(self.for_action(action)) for action in SyncAction}

    def to_dict(self, *, include_items: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {"counts": self.counts()}
        if include_items:
            value["items"] = [item.to_dict() for item in self.items]
        return value


@dataclass(frozen=True)
class WikiSyncResult:
    dry_run: bool
    sync_run_id: str | None
    source_id: str | None
    plan: WikiSyncPlan
    scope: str = "full"
    requested_titles: tuple[str, ...] = ()
    created_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    removed_count: int = 0
    failed_count: int = 0
    failures: tuple[str, ...] = ()

    def to_dict(self, *, include_items: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "dry_run": self.dry_run,
            "sync_run_id": self.sync_run_id,
            "source_id": self.source_id,
            "scope": self.scope,
            "requested_titles": list(self.requested_titles),
            "plan": self.plan.to_dict(include_items=include_items),
        }
        if not self.dry_run:
            value["execution"] = {
                "created": self.created_count,
                "updated": self.updated_count,
                "unchanged": self.unchanged_count,
                "removed": self.removed_count,
                "failed": self.failed_count,
                "failures": list(self.failures),
            }
        return value


def _parse_categories(raw_value: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return ()
    return tuple(sorted(str(item) for item in value)) if isinstance(value, list) else ()


def _parse_wiki_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def select_references_by_titles(
    references: list[WikiPageReference], requested_titles: tuple[str, ...]
) -> list[WikiPageReference]:
    """从完整允许范围中按标题选择页面，并保持命令行指定顺序。"""

    by_title = {reference.title.casefold(): reference for reference in references}
    selected: list[WikiPageReference] = []
    missing: list[str] = []
    for title in requested_titles:
        reference = by_title.get(title.casefold())
        if reference is None:
            missing.append(title)
        else:
            selected.append(reference)
    if missing:
        raise ValueError(
            "以下页面不存在或不属于允许的建筑/小动物分类: " + "、".join(missing)
        )
    return selected


def build_sync_plan(
    references: list[WikiPageReference],
    revisions: dict[int, WikiPageRevision],
    local_pages: list[LocalWikiPageState],
    *,
    detect_removals: bool = True,
) -> WikiSyncPlan:
    """Pure comparison logic shared by dry-run and real synchronization."""

    missing_revision_ids = {reference.page_id for reference in references} - set(revisions)
    if missing_revision_ids:
        missing = ", ".join(str(page_id) for page_id in sorted(missing_revision_ids))
        raise MediaWikiAPIError(f"以下页面缺少修订元数据: {missing}")

    local_by_page_id = {page.page_id: page for page in local_pages}
    remote_page_ids: set[int] = set()
    items: list[SyncPlanItem] = []

    for reference in references:
        remote_page_ids.add(reference.page_id)
        revision = revisions[reference.page_id]
        local = local_by_page_id.get(reference.page_id)
        if local is None:
            action = SyncAction.CREATE
        else:
            metadata_changed = (
                local.title != revision.title
                or local.canonical_url != revision.canonical_url
                or local.categories != tuple(sorted(reference.categories))
            )
            action = (
                SyncAction.UPDATE
                if local.revision_id != revision.revision_id
                or metadata_changed
                or local.document_status == "source_removed"
                else SyncAction.UNCHANGED
            )
        items.append(
            SyncPlanItem(
                action=action,
                page_id=reference.page_id,
                title=revision.title,
                remote_revision_id=revision.revision_id,
                local_revision_id=local.revision_id if local else None,
                categories=tuple(sorted(reference.categories)),
                document_id=local.document_id if local else None,
            )
        )

    for local in local_pages:
        # 已经标记过的下线页面不重复计入后续同步统计。
        if (
            detect_removals
            and local.page_id not in remote_page_ids
            and local.document_status != "source_removed"
        ):
            items.append(
                SyncPlanItem(
                    action=SyncAction.REMOVE,
                    page_id=local.page_id,
                    title=local.title,
                    remote_revision_id=None,
                    local_revision_id=local.revision_id,
                    categories=local.categories,
                    document_id=local.document_id,
                )
            )

    return WikiSyncPlan(items=tuple(sorted(items, key=lambda item: (item.action.value, item.page_id))))


class WikiSyncService:
    def __init__(
        self,
        *,
        client: MediaWikiClient | None = None,
        snapshot_store: WikiSnapshotStore | None = None,
        session_factory: sessionmaker | None = None,
    ) -> None:
        self.settings = get_settings()
        self.client = client or MediaWikiClient()
        self._owns_client = client is None
        self.snapshot_store = snapshot_store or WikiSnapshotStore()
        self.session_factory = session_factory or get_session_factory()

    def _find_source(self) -> WikiSource | None:
        with self.session_factory() as session:
            return session.scalar(
                select(WikiSource).where(WikiSource.api_url == self.settings.mediawiki_api_url)
            )

    def _ensure_source_and_run(
        self, requested_titles: tuple[str, ...]
    ) -> tuple[WikiSource, WikiSyncRun]:
        with self.session_factory() as session:
            source = session.scalar(
                select(WikiSource).where(WikiSource.api_url == self.settings.mediawiki_api_url)
            )
            if source is None:
                source = WikiSource(id=str(uuid4()), api_url=self.settings.mediawiki_api_url)
                session.add(source)

            source.name = SOURCE_NAME
            source.base_url = self.settings.mediawiki_base_url
            source.language = self.settings.mediawiki_language
            source.root_categories_json = json.dumps(
                self.settings.mediawiki_root_categories, ensure_ascii=False
            )
            source.excluded_category_keywords_json = json.dumps(
                self.settings.mediawiki_excluded_category_keywords, ensure_ascii=False
            )
            source.license_name = LICENSE_NAME
            source.license_url = LICENSE_URL
            source.status = "active"

            sync_run = WikiSyncRun(
                id=str(uuid4()),
                source_id=source.id,
                scope="partial" if requested_titles else "full",
                requested_titles_json=(
                    json.dumps(requested_titles, ensure_ascii=False)
                    if requested_titles
                    else None
                ),
                status="running",
            )
            session.add(sync_run)
            session.commit()
            session.refresh(source)
            session.refresh(sync_run)
            return source, sync_run

    def _load_local_pages(self, source_id: str | None) -> list[LocalWikiPageState]:
        if source_id is None:
            return []
        with self.session_factory() as session:
            rows = session.execute(
                select(WikiPageRecord, DocumentRecord)
                .join(DocumentRecord, DocumentRecord.id == WikiPageRecord.document_id)
                .where(WikiPageRecord.source_id == source_id)
            ).all()
            return [
                LocalWikiPageState(
                    page_record_id=page.id,
                    document_id=document.id,
                    page_id=page.page_id,
                    revision_id=page.revision_id,
                    title=page.title,
                    canonical_url=page.canonical_url,
                    categories=_parse_categories(page.categories_json),
                    document_status=document.status,
                )
                for page, document in rows
            ]

    def _set_run_failed(self, sync_run_id: str, message: str) -> None:
        with self.session_factory() as session:
            sync_run = session.get(WikiSyncRun, sync_run_id)
            if sync_run is not None:
                sync_run.status = "failed"
                sync_run.error_message = message[:4000]
                sync_run.completed_at = utc_now()
                session.commit()

    def _upsert_page(
        self,
        source_id: str,
        item: SyncPlanItem,
        *,
        payload: WikiPagePayload,
        snapshot: SnapshotRecord,
    ) -> None:
        with self.session_factory() as session:
            page = session.scalar(
                select(WikiPageRecord).where(
                    WikiPageRecord.source_id == source_id,
                    WikiPageRecord.page_id == item.page_id,
                )
            )
            if page is None:
                document = DocumentRecord(
                    id=str(uuid4()),
                    filename=payload.title,
                    content_type="text/html",
                    size_bytes=snapshot.size_bytes,
                    status="pending_index",
                    chunk_count=0,
                )
                session.add(document)
                session.flush()
                page = WikiPageRecord(
                    id=str(uuid4()),
                    document_id=document.id,
                    source_id=source_id,
                    page_id=payload.page_id,
                    indexed_revision_id=None,
                )
                session.add(page)
            else:
                document = session.get(DocumentRecord, page.document_id)
                if document is None:
                    raise RuntimeError(f"Wiki 页面缺少 documents 记录: page_id={item.page_id}")
                document.filename = payload.title
                document.content_type = "text/html"
                document.size_bytes = snapshot.size_bytes
                document.status = "pending_index"
                document.error_message = None

            page.revision_id = payload.revision_id
            page.title = payload.title
            page.canonical_url = payload.canonical_url
            page.namespace = 0
            page.categories_json = json.dumps(item.categories, ensure_ascii=False)
            page.content_sha256 = snapshot.content_sha256
            page.snapshot_path = snapshot.path
            page.source_updated_at = _parse_wiki_timestamp(payload.revision_timestamp)
            page.synced_at = utc_now()
            session.commit()

    def _mark_removed(self, item: SyncPlanItem) -> None:
        if item.document_id is None:
            return
        with self.session_factory() as session:
            document = session.get(DocumentRecord, item.document_id)
            if document is not None:
                document.status = "source_removed"
                document.error_message = None
                session.commit()

    def _finish_run(
        self,
        *,
        source_id: str,
        sync_run_id: str,
        discovered_count: int,
        created_count: int,
        updated_count: int,
        unchanged_count: int,
        removed_count: int,
        failures: list[str],
        update_full_sync_timestamp: bool,
    ) -> None:
        with self.session_factory() as session:
            source = session.get(WikiSource, source_id)
            sync_run = session.get(WikiSyncRun, sync_run_id)
            completed_at = utc_now()
            if source is not None and update_full_sync_timestamp and not failures:
                source.last_synced_at = completed_at
            if sync_run is not None:
                sync_run.status = "completed" if not failures else "completed_with_errors"
                sync_run.discovered_count = discovered_count
                sync_run.created_count = created_count
                sync_run.updated_count = updated_count
                sync_run.unchanged_count = unchanged_count
                sync_run.removed_count = removed_count
                sync_run.failed_count = len(failures)
                sync_run.error_message = "\n".join(failures)[:4000] if failures else None
                sync_run.completed_at = completed_at
            session.commit()

    async def run(
        self, *, dry_run: bool = False, titles: list[str] | tuple[str, ...] | None = None
    ) -> WikiSyncResult:
        requested_titles = tuple(
            dict.fromkeys(title.strip() for title in (titles or []) if title.strip())
        )
        if titles and not requested_titles:
            raise ValueError("--title 不能为空")
        partial_sync = bool(requested_titles)
        source = self._find_source() if dry_run else None
        sync_run = None
        if not dry_run:
            source, sync_run = self._ensure_source_and_run(requested_titles)

        try:
            references = await self.client.discover_pages(self.settings.mediawiki_root_categories)
            if partial_sync:
                references = select_references_by_titles(references, requested_titles)
            revisions = await self.client.fetch_revisions(
                [reference.page_id for reference in references]
            )
            local_pages = self._load_local_pages(source.id if source else None)
            plan = build_sync_plan(
                references,
                revisions,
                local_pages,
                detect_removals=not partial_sync,
            )

            if dry_run:
                return WikiSyncResult(
                    dry_run=True,
                    sync_run_id=None,
                    source_id=source.id if source else None,
                    plan=plan,
                    scope="partial" if partial_sync else "full",
                    requested_titles=requested_titles,
                )

            assert source is not None and sync_run is not None
            created_count = 0
            updated_count = 0
            removed_count = 0
            failures: list[str] = []

            for item in plan.items:
                if item.action == SyncAction.UNCHANGED:
                    continue
                if item.action == SyncAction.REMOVE:
                    self._mark_removed(item)
                    removed_count += 1
                    continue
                try:
                    payload = await self.client.fetch_page(item.page_id)
                    snapshot = self.snapshot_store.write(
                        payload,
                        categories=item.categories,
                        source_name=source.name,
                        api_url=source.api_url,
                        license_name=source.license_name or LICENSE_NAME,
                        license_url=source.license_url or LICENSE_URL,
                    )
                    self._upsert_page(
                        source.id,
                        item,
                        payload=payload,
                        snapshot=snapshot,
                    )
                    if item.action == SyncAction.CREATE:
                        created_count += 1
                    else:
                        updated_count += 1
                except Exception as exc:
                    logger.exception("Wiki page snapshot failed page_id=%d", item.page_id)
                    failures.append(f"page_id={item.page_id}: {exc}")

            unchanged_count = len(plan.for_action(SyncAction.UNCHANGED))
            self._finish_run(
                source_id=source.id,
                sync_run_id=sync_run.id,
                discovered_count=len(references),
                created_count=created_count,
                updated_count=updated_count,
                unchanged_count=unchanged_count,
                removed_count=removed_count,
                failures=failures,
                update_full_sync_timestamp=not partial_sync,
            )
            return WikiSyncResult(
                dry_run=False,
                sync_run_id=sync_run.id,
                source_id=source.id,
                plan=plan,
                scope="partial" if partial_sync else "full",
                requested_titles=requested_titles,
                created_count=created_count,
                updated_count=updated_count,
                unchanged_count=unchanged_count,
                removed_count=removed_count,
                failed_count=len(failures),
                failures=tuple(failures),
            )
        except Exception as exc:
            if sync_run is not None:
                self._set_run_failed(sync_run.id, str(exc))
            raise
        finally:
            if self._owns_client:
                await self.client.aclose()
