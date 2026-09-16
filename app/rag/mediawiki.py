"""Async MediaWiki API client for page discovery and revision retrieval."""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings


class MediaWikiAPIError(RuntimeError):
    """MediaWiki 返回错误响应或缺少预期数据。"""


@dataclass(frozen=True)
class WikiPageReference:
    page_id: int
    title: str
    categories: tuple[str, ...]


@dataclass(frozen=True)
class WikiPagePayload:
    page_id: int
    revision_id: int
    title: str
    canonical_url: str
    revision_timestamp: str
    wikitext: str
    html: str


@dataclass(frozen=True)
class WikiPageRevision:
    page_id: int
    revision_id: int
    title: str
    canonical_url: str
    revision_timestamp: str


def normalize_category_name(value: str) -> str:
    """接受“Category:建筑”“分类:建筑”或“建筑”三种写法。"""

    value = value.strip()
    for prefix in ("Category:", "分类:"):
        if value.casefold().startswith(prefix.casefold()):
            return value[len(prefix) :].strip()
    return value


class MediaWikiClient:
    """封装分页、分类递归和页面修订读取，不负责数据库或向量写入。"""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        excluded_category_keywords: list[str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.api_url = api_url or settings.mediawiki_api_url
        self.excluded_category_keywords = tuple(
            keyword.casefold()
            for keyword in (
                excluded_category_keywords
                if excluded_category_keywords is not None
                else settings.mediawiki_excluded_category_keywords
            )
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.mediawiki_request_timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.mediawiki_user_agent},
        )

    async def __aenter__(self) -> "MediaWikiClient":
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def category_is_excluded(self, category: str) -> bool:
        folded = normalize_category_name(category).casefold()
        return any(keyword in folded for keyword in self.excluded_category_keywords)

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        # 所有请求串行执行，并携带 maxlag；遇到限流、临时服务错误或站点高负载时退避重试。
        for attempt in range(3):
            try:
                response = await self._client.get(
                    self.api_url,
                    params={"format": "json", "formatversion": 2, "maxlag": 5, **params},
                )
                response.raise_for_status()
                payload = response.json()
                error = payload.get("error")
                if error and error.get("code") == "maxlag" and attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                if error:
                    raise MediaWikiAPIError(
                        f"MediaWiki API 错误 {error.get('code', 'unknown')}: "
                        f"{error.get('info', '没有详细信息')}"
                    )
                return payload
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.TransportError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in {429, 500, 502, 503, 504}
                )
                if not retryable or attempt == 2:
                    raise MediaWikiAPIError(f"MediaWiki 请求失败: {exc}") from exc
                await asyncio.sleep(2**attempt)

        raise MediaWikiAPIError("MediaWiki 请求重试次数已耗尽")

    async def category_members(self, category: str) -> list[dict[str, Any]]:
        """读取一个分类的所有正文页面和子分类，自动处理 API continuation。"""

        members: list[dict[str, Any]] = []
        continuation: dict[str, Any] = {}
        while True:
            payload = await self._request(
                {
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": f"Category:{normalize_category_name(category)}",
                    "cmnamespace": "0|14",
                    "cmtype": "page|subcat",
                    "cmlimit": "max",
                    **continuation,
                }
            )
            members.extend(payload.get("query", {}).get("categorymembers", []))
            continuation = payload.get("continue", {})
            if not continuation:
                return members

    async def discover_pages(self, root_categories: list[str]) -> list[WikiPageReference]:
        """递归遍历分类树，对跨分类重复出现的页面按 page_id 去重。"""

        pending = [normalize_category_name(category) for category in root_categories]
        visited_categories: set[str] = set()
        pages: dict[int, tuple[str, set[str]]] = {}

        while pending:
            category = pending.pop(0)
            category_key = category.casefold()
            if category_key in visited_categories or self.category_is_excluded(category):
                continue
            visited_categories.add(category_key)

            for member in await self.category_members(category):
                namespace = int(member.get("ns", -1))
                if namespace == 14:
                    child_category = normalize_category_name(str(member.get("title", "")))
                    if child_category and not self.category_is_excluded(child_category):
                        pending.append(child_category)
                    continue
                if namespace != 0:
                    continue

                page_id = int(member["pageid"])
                title = str(member["title"])
                existing = pages.get(page_id)
                if existing is None:
                    pages[page_id] = (title, {category})
                else:
                    existing[1].add(category)

        return [
            WikiPageReference(
                page_id=page_id,
                title=title,
                categories=tuple(sorted(categories)),
            )
            for page_id, (title, categories) in sorted(pages.items())
        ]

    async def fetch_revisions(
        self, page_ids: list[int], *, batch_size: int = 50
    ) -> dict[int, WikiPageRevision]:
        """批量读取轻量修订元数据，避免为未变化页面下载正文和 HTML。"""

        if not 1 <= batch_size <= 50:
            raise ValueError("batch_size 必须在 1 到 50 之间")

        revisions: dict[int, WikiPageRevision] = {}
        for offset in range(0, len(page_ids), batch_size):
            batch = page_ids[offset : offset + batch_size]
            payload = await self._request(
                {
                    "action": "query",
                    "pageids": "|".join(str(page_id) for page_id in batch),
                    "prop": "info|revisions",
                    "inprop": "url",
                    "rvprop": "ids|timestamp",
                }
            )
            for page in payload.get("query", {}).get("pages", []):
                page_revisions = page.get("revisions", [])
                if page.get("missing") or not page_revisions:
                    continue
                revision = page_revisions[0]
                page_id = int(page["pageid"])
                revisions[page_id] = WikiPageRevision(
                    page_id=page_id,
                    revision_id=int(revision["revid"]),
                    title=str(page["title"]),
                    canonical_url=str(page.get("fullurl", "")),
                    revision_timestamp=str(revision["timestamp"]),
                )
        return revisions

    async def fetch_page(self, page_id: int) -> WikiPagePayload:
        """同时读取原始 wikitext、修订号和 MediaWiki 渲染后的 HTML。"""

        revision_payload = await self._request(
            {
                "action": "query",
                "pageids": str(page_id),
                "prop": "info|revisions",
                "inprop": "url",
                "rvprop": "ids|timestamp|content",
                "rvslots": "main",
                "redirects": 1,
            }
        )
        pages = revision_payload.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            raise MediaWikiAPIError(f"Wiki 页面不存在: page_id={page_id}")

        page = pages[0]
        revisions = page.get("revisions", [])
        if not revisions:
            raise MediaWikiAPIError(f"Wiki 页面缺少修订内容: page_id={page_id}")
        revision = revisions[0]
        main_slot = revision.get("slots", {}).get("main", {})

        parse_payload = await self._request(
            {
                "action": "parse",
                "pageid": str(page_id),
                "prop": "text",
            }
        )
        parsed = parse_payload.get("parse", {})
        return WikiPagePayload(
            page_id=int(page["pageid"]),
            revision_id=int(revision["revid"]),
            title=str(page["title"]),
            canonical_url=str(page.get("fullurl", "")),
            revision_timestamp=str(revision["timestamp"]),
            wikitext=str(main_slot.get("content", "")),
            html=str(parsed.get("text", "")),
        )
