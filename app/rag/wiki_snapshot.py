"""Immutable on-disk snapshots for MediaWiki revisions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, get_settings
from app.rag.mediawiki import WikiPagePayload


class SnapshotConflictError(RuntimeError):
    """同一 page_id/revision_id 已存在但内容不同。"""


@dataclass(frozen=True)
class SnapshotRecord:
    path: str
    size_bytes: int
    content_sha256: str


class WikiSnapshotStore:
    def __init__(self, root: str | Path | None = None) -> None:
        configured_root = Path(root or get_settings().mediawiki_snapshot_path)
        self.root = (
            configured_root
            if configured_root.is_absolute()
            else (PROJECT_ROOT / configured_root).resolve()
        )

    def _target(self, page_id: int, revision_id: int) -> Path:
        return self.root / str(page_id) / f"{revision_id}.json"

    @staticmethod
    def _content_hash(payload: WikiPagePayload) -> str:
        # revision_id 是远端版本依据，内容哈希用于检测缓存损坏或异常响应。
        return sha256(payload.wikitext.encode("utf-8")).hexdigest()

    def _stored_path(self, target: Path) -> str:
        try:
            return target.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return str(target)

    def _record_for_existing(
        self, target: Path, payload: WikiPagePayload, content_hash: str
    ) -> SnapshotRecord:
        try:
            existing: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SnapshotConflictError(f"已有 Wiki 快照无法读取: {target}") from exc

        page = existing.get("page", {})
        if (
            page.get("page_id") != payload.page_id
            or page.get("revision_id") != payload.revision_id
            or existing.get("content_sha256") != content_hash
            or existing.get("wikitext") != payload.wikitext
            or existing.get("html") != payload.html
        ):
            raise SnapshotConflictError(f"Wiki 快照内容冲突，拒绝覆盖: {target}")
        return SnapshotRecord(
            path=self._stored_path(target),
            size_bytes=target.stat().st_size,
            content_sha256=content_hash,
        )

    def write(
        self,
        payload: WikiPagePayload,
        *,
        categories: tuple[str, ...],
        source_name: str,
        api_url: str,
        license_name: str,
        license_url: str,
    ) -> SnapshotRecord:
        content_hash = self._content_hash(payload)
        target = self._target(payload.page_id, payload.revision_id)
        if target.exists():
            return self._record_for_existing(target, payload, content_hash)

        snapshot = {
            "schema_version": 1,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "name": source_name,
                "api_url": api_url,
                "license_name": license_name,
                "license_url": license_url,
            },
            "page": {
                "page_id": payload.page_id,
                "revision_id": payload.revision_id,
                "title": payload.title,
                "canonical_url": payload.canonical_url,
                "revision_timestamp": payload.revision_timestamp,
                "categories": list(categories),
            },
            "content_sha256": content_hash,
            "wikitext": payload.wikitext,
            "html": payload.html,
        }
        serialized = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # x 模式保证不会覆盖并发任务已经写入的相同修订。
            with target.open("x", encoding="utf-8", newline="\n") as snapshot_file:
                snapshot_file.write(serialized)
        except FileExistsError:
            return self._record_for_existing(target, payload, content_hash)

        return SnapshotRecord(
            path=self._stored_path(target),
            size_bytes=target.stat().st_size,
            content_sha256=content_hash,
        )
