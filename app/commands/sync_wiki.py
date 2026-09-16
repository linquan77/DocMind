"""Synchronize configured MediaWiki page metadata and raw snapshots."""

import argparse
import asyncio
import json
import logging
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.wiki_sync_service import WikiSyncService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="发现缺氧中文 Wiki 页面，并增量保存原始修订快照。"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只输出新增、更新、未变化和下线计划，不写数据库和快照文件。",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="除统计摘要外，列出每个页面的增量计划。",
    )
    parser.add_argument(
        "--title",
        action="append",
        default=[],
        metavar="TITLE",
        help="只同步指定页面，可重复使用；部分同步不会判断其他页面下线。",
    )
    return parser


async def _run(dry_run: bool, verbose: bool, titles: list[str]) -> int:
    result = await WikiSyncService().run(dry_run=dry_run, titles=titles)
    print(json.dumps(result.to_dict(include_items=verbose), ensure_ascii=False, indent=2))
    return 1 if result.failed_count else 0


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(get_settings().log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        return asyncio.run(_run(args.dry_run, args.verbose, args.title))
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
