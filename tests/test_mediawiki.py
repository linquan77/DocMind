import asyncio

import httpx

from app.rag.mediawiki import MediaWikiClient


def test_discover_pages_recurses_deduplicates_and_excludes_categories():
    requested_categories: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        category = request.url.params["cmtitle"]
        requested_categories.append(category)
        responses = {
            "Category:建筑": {
                "batchcomplete": True,
                "query": {
                    "categorymembers": [
                        {"pageid": 10, "ns": 0, "title": "电解器"},
                        {"pageid": 100, "ns": 14, "title": "Category:电力建筑"},
                        {"pageid": 101, "ns": 14, "title": "Category:调试建筑"},
                    ]
                },
            },
            "Category:电力建筑": {
                "batchcomplete": True,
                "query": {
                    "categorymembers": [
                        {"pageid": 10, "ns": 0, "title": "电解器"},
                        {"pageid": 11, "ns": 0, "title": "人力发电机"},
                    ]
                },
            },
            "Category:小动物": {
                "batchcomplete": True,
                "query": {
                    "categorymembers": [
                        {"pageid": 20, "ns": 0, "title": "哈奇"},
                    ]
                },
            },
        }
        return httpx.Response(200, json=responses[category])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = MediaWikiClient(
                api_url="https://example.test/api.php",
                excluded_category_keywords=["调试"],
                client=http_client,
            )
            return await client.discover_pages(["建筑", "小动物"])

    pages = asyncio.run(run())

    assert [page.page_id for page in pages] == [10, 11, 20]
    assert pages[0].categories == ("建筑", "电力建筑")
    assert "Category:调试建筑" not in requested_categories


def test_fetch_page_returns_revision_and_rendered_html():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["action"] == "query":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "pageid": 10,
                                "title": "电解器",
                                "fullurl": "https://example.test/wiki/电解器",
                                "revisions": [
                                    {
                                        "revid": 99,
                                        "timestamp": "2026-09-13T00:00:00Z",
                                        "slots": {"main": {"content": "'''电解器'''"}},
                                    }
                                ],
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"parse": {"text": "<p>电解器</p>"}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = MediaWikiClient(
                api_url="https://example.test/api.php",
                client=http_client,
            )
            return await client.fetch_page(10)

    page = asyncio.run(run())

    assert page.page_id == 10
    assert page.revision_id == 99
    assert page.wikitext == "'''电解器'''"
    assert page.html == "<p>电解器</p>"


def test_fetch_revisions_batches_page_ids():
    requested_batches: list[list[int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_ids = [int(value) for value in request.url.params["pageids"].split("|")]
        requested_batches.append(page_ids)
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": page_id,
                            "title": f"页面 {page_id}",
                            "fullurl": f"https://example.test/wiki/{page_id}",
                            "revisions": [
                                {
                                    "revid": page_id * 10,
                                    "timestamp": "2026-09-13T00:00:00Z",
                                }
                            ],
                        }
                        for page_id in page_ids
                    ]
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = MediaWikiClient(
                api_url="https://example.test/api.php",
                client=http_client,
            )
            return await client.fetch_revisions([1, 2, 3], batch_size=2)

    revisions = asyncio.run(run())

    assert requested_batches == [[1, 2], [3]]
    assert revisions[3].revision_id == 30
