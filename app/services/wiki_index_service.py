"""Orchestrate Wiki snapshot parsing, splitting, and versioned indexing."""

from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import PROJECT_ROOT
from app.core.database import get_session_factory
from app.models.document import DocumentRecord
from app.models.wiki import WikiPageRecord
from app.rag.splitter import split_wiki_page
from app.rag.vectorstore import replace_wiki_revision_chunks
from app.rag.wiki_parser import parse_wiki_snapshot


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WikiIndexPlanItem:
    page_record_id: str
    document_id: str
    page_id: int
    title: str
    revision_id: int
    indexed_revision_id: int | None
    snapshot_path: str
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "page_id": self.page_id,
            "title": self.title,
            "revision_id": self.revision_id,
            "indexed_revision_id": self.indexed_revision_id,
            "snapshot_path": self.snapshot_path,
        }


@dataclass(frozen=True)
class WikiIndexResult:
    dry_run: bool
    planned_items: tuple[WikiIndexPlanItem, ...]
    skipped_count: int
    deferred_count: int
    indexed_count: int = 0
    chunk_count: int = 0
    removed_old_chunk_count: int = 0
    failed_count: int = 0
    failures: tuple[str, ...] = ()

    def to_dict(self, *, include_items: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "dry_run": self.dry_run,
            "plan": {
                "planned": len(self.planned_items),
                "skipped_up_to_date": self.skipped_count,
                "deferred_by_limit": self.deferred_count,
            },
        }
        if include_items:
            value["plan"]["items"] = [item.to_dict() for item in self.planned_items]
        if not self.dry_run:
            value["execution"] = {
                "indexed": self.indexed_count,
                "chunks_added": self.chunk_count,
                "old_chunks_removed": self.removed_old_chunk_count,
                "failed": self.failed_count,
                "failures": list(self.failures),
            }
        return value


class WikiIndexService:
    def __init__(self, *, session_factory: sessionmaker | None = None) -> None:
        self.session_factory = session_factory or get_session_factory()

    def _load_items(
        self, requested_titles: tuple[str, ...]
    ) -> tuple[list[WikiIndexPlanItem], int]:
        with self.session_factory() as session:
            rows = session.execute(
                select(WikiPageRecord, DocumentRecord)
                .join(DocumentRecord, DocumentRecord.id == WikiPageRecord.document_id)
                .order_by(WikiPageRecord.title, WikiPageRecord.page_id)
            ).all()

        all_items = [
            WikiIndexPlanItem(
                page_record_id=page.id,
                document_id=document.id,
                page_id=page.page_id,
                title=page.title,
                revision_id=page.revision_id,
                indexed_revision_id=page.indexed_revision_id,
                snapshot_path=page.snapshot_path,
                content_sha256=page.content_sha256,
            )
            for page, document in rows
            if document.status != "source_removed"
        ]

        if requested_titles:
            by_title = {item.title.casefold(): item for item in all_items}
            missing = [title for title in requested_titles if title.casefold() not in by_title]
            if missing:
                raise ValueError("以下 Wiki 页面不存在或已下线: " + "、".join(missing))
            selected = [by_title[title.casefold()] for title in requested_titles]
        else:
            selected = all_items

        pending = [
            item for item in selected if item.indexed_revision_id != item.revision_id
        ]
        return pending, len(selected) - len(pending)

    def _mark_indexing(self, item: WikiIndexPlanItem) -> None:
        with self.session_factory() as session:
            document = session.get(DocumentRecord, item.document_id)
            if document is None:
                raise RuntimeError(f"Wiki 页面缺少 documents 记录: page_id={item.page_id}")
            document.status = "indexing"
            document.error_message = None
            session.commit()

    def _mark_ready(self, item: WikiIndexPlanItem, chunk_count: int) -> None:
        with self.session_factory() as session:
            page = session.get(WikiPageRecord, item.page_record_id)
            document = session.get(DocumentRecord, item.document_id)
            if page is None or document is None:
                raise RuntimeError(f"Wiki 索引记录在处理期间被删除: page_id={item.page_id}")
            if page.revision_id != item.revision_id:
                raise RuntimeError(
                    f"Wiki 页面在索引期间出现新修订: page_id={item.page_id}, "
                    f"expected={item.revision_id}, actual={page.revision_id}"
                )
            page.indexed_revision_id = item.revision_id
            document.status = "ready"
            document.chunk_count = chunk_count
            document.error_message = None
            session.commit()

    def _mark_failed(self, item: WikiIndexPlanItem, message: str) -> None:
        with self.session_factory() as session:
            document = session.get(DocumentRecord, item.document_id)
            if document is not None:
                document.status = "index_failed"
                document.error_message = message[:4000]
                session.commit()

    @staticmethod
    def _resolve_snapshot_path(snapshot_path: str) -> Path:
        path = Path(snapshot_path)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @staticmethod
    def _validate_snapshot(item: WikiIndexPlanItem, page) -> None:
        if page.page_id != item.page_id:
            raise ValueError(
                f"快照 page_id 不匹配: expected={item.page_id}, actual={page.page_id}"
            )
        if page.revision_id != item.revision_id:
            raise ValueError(
                "快照 revision_id 不匹配: "
                f"expected={item.revision_id}, actual={page.revision_id}"
            )
        if item.content_sha256 and page.content_sha256 != item.content_sha256:
            raise ValueError(f"快照内容哈希不匹配: page_id={item.page_id}")

    def run(
        self,
        *,
        dry_run: bool = False,
        titles: list[str] | tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> WikiIndexResult:
        started = time.perf_counter()
        requested_titles = tuple(
            dict.fromkeys(title.strip() for title in (titles or []) if title.strip())
        )
        if titles and not requested_titles:
            raise ValueError("--title 不能为空")
        if limit is not None and limit < 1:
            raise ValueError("--limit 必须大于 0")

        pending_items, skipped_count = self._load_items(requested_titles)
        deferred_count = max(0, len(pending_items) - limit) if limit else 0
        planned_items = pending_items[:limit] if limit else pending_items

        if dry_run:
            return WikiIndexResult(
                dry_run=True,
                planned_items=tuple(planned_items),
                skipped_count=skipped_count,
                deferred_count=deferred_count,
            )

        indexed_count = 0
        chunk_count = 0
        removed_old_chunk_count = 0
        failures: list[str] = []

        for item in planned_items:
            try:
                self._mark_indexing(item)
                parsed_page = parse_wiki_snapshot(
                    self._resolve_snapshot_path(item.snapshot_path)
                )
                self._validate_snapshot(item, parsed_page)
                chunks = split_wiki_page(parsed_page, document_id=item.document_id)
                if not chunks:
                    raise ValueError(f"Wiki 页面没有可索引切块: page_id={item.page_id}")
                # 解析时使用绝对路径保证任意工作目录都能读取文件；写入 Chroma 时恢复
                # SQLite 中的规范路径，避免向量元数据绑定某台开发机的目录。
                portable_snapshot_path = item.snapshot_path.replace("\\", "/")
                for chunk in chunks:
                    chunk.metadata["snapshot_path"] = portable_snapshot_path
                added_count, removed_count = replace_wiki_revision_chunks(
                    chunks,
                    page_id=item.page_id,
                    revision_id=item.revision_id,
                    previous_revision_id=item.indexed_revision_id,
                )
                self._mark_ready(item, added_count)
                indexed_count += 1
                chunk_count += added_count
                removed_old_chunk_count += removed_count
                logger.info(
                    "Wiki page indexed page_id=%d revision_id=%d chunks=%d old_chunks_removed=%d",
                    item.page_id,
                    item.revision_id,
                    added_count,
                    removed_count,
                )
            except Exception as exc:
                logger.exception(
                    "Wiki page indexing failed page_id=%d revision_id=%d",
                    item.page_id,
                    item.revision_id,
                )
                message = f"page_id={item.page_id}, title={item.title}: {exc}"
                failures.append(message)
                self._mark_failed(item, str(exc))

        logger.info(
            "Wiki indexing completed planned=%d indexed=%d failed=%d chunks=%d latency_ms=%d",
            len(planned_items),
            indexed_count,
            len(failures),
            chunk_count,
            int((time.perf_counter() - started) * 1000),
        )
        return WikiIndexResult(
            dry_run=False,
            planned_items=tuple(planned_items),
            skipped_count=skipped_count,
            deferred_count=deferred_count,
            indexed_count=indexed_count,
            chunk_count=chunk_count,
            removed_old_chunk_count=removed_old_chunk_count,
            failed_count=len(failures),
            failures=tuple(failures),
        )
