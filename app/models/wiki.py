"""MediaWiki-specific metadata used for incremental synchronization."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.document import utc_now


class WikiSource(Base):
    """一个可同步的 MediaWiki 站点及其抓取规则。"""

    __tablename__ = "wiki_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False, default="zh")
    root_categories_json: Mapped[str] = mapped_column(Text, nullable=False)
    excluded_category_keywords_json: Mapped[str] = mapped_column(Text, nullable=False)
    license_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    license_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class WikiPageRecord(Base):
    """Wiki 页面与通用 documents 记录之间的一对一映射。"""

    __tablename__ = "wiki_pages"
    __table_args__ = (
        UniqueConstraint("source_id", "page_id", name="uq_wiki_pages_source_page"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("wiki_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 快照下载和向量索引分阶段进行；为空表示当前快照尚未进入 Chroma。
    indexed_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    namespace: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    categories_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WikiSyncRun(Base):
    """一次全量发现或增量同步的审计记录。"""

    __tablename__ = "wiki_sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("wiki_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="full", index=True)
    requested_titles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", index=True)
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
