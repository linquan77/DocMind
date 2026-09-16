import json

import pytest

from app.rag.mediawiki import WikiPagePayload
from app.rag.wiki_snapshot import SnapshotConflictError, WikiSnapshotStore


def make_payload(*, wikitext: str = "'''电解器'''用于将水分解。") -> WikiPagePayload:
    return WikiPagePayload(
        page_id=123,
        revision_id=456,
        title="电解器",
        canonical_url="https://example.test/wiki/电解器",
        revision_timestamp="2026-09-13T00:00:00Z",
        wikitext=wikitext,
        html="<p>电解器用于将水分解。</p>",
    )


def test_snapshot_is_immutable_and_reuses_identical_revision(tmp_path):
    store = WikiSnapshotStore(tmp_path)
    payload = make_payload()

    first = store.write(
        payload,
        categories=("建筑",),
        source_name="缺氧 Wiki（中文）",
        api_url="https://example.test/api.php",
        license_name="CC BY-NC-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-nc-sa/4.0/",
    )
    second = store.write(
        payload,
        categories=("建筑",),
        source_name="缺氧 Wiki（中文）",
        api_url="https://example.test/api.php",
        license_name="CC BY-NC-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-nc-sa/4.0/",
    )

    target = tmp_path / "123" / "456.json"
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert first == second
    assert saved["page"]["categories"] == ["建筑"]
    assert saved["content_sha256"] == first.content_sha256
    assert saved["wikitext"] == payload.wikitext


def test_snapshot_refuses_to_overwrite_conflicting_revision(tmp_path):
    store = WikiSnapshotStore(tmp_path)
    common = {
        "categories": ("建筑",),
        "source_name": "缺氧 Wiki（中文）",
        "api_url": "https://example.test/api.php",
        "license_name": "CC BY-NC-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    }
    store.write(make_payload(), **common)

    with pytest.raises(SnapshotConflictError):
        store.write(make_payload(wikitext="发生冲突的内容"), **common)
