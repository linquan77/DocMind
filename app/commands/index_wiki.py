"""Index synchronized Wiki snapshots into Chroma."""

import argparse
import json
import logging
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.wiki_index_service import WikiIndexService


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="解析已同步的 Wiki 快照，并按修订版本写入 Chroma。"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出待索引页面，不修改 SQLite 或 Chroma。",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="除统计摘要外，列出每个待索引页面。",
    )
    parser.add_argument(
        "--title",
        action="append",
        default=[],
        metavar="TITLE",
        help="只索引指定页面，可重复使用。",
    )
    parser.add_argument(
        "--limit",
        type=positive_integer,
        help="本次最多索引的页面数量。",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(get_settings().log_level)
    try:
        result = WikiIndexService().run(
            dry_run=args.dry_run,
            titles=args.title,
            limit=args.limit,
        )
        print(
            json.dumps(
                result.to_dict(include_items=args.verbose),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if result.failed_count else 0
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
