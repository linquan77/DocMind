"""Randomly sample Chroma chunks for manual quality inspection."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
import random
import sys
from typing import Any

from app.core.config import get_settings
from app.rag.vectorstore import get_chroma_client


DEFAULT_SAMPLE_COUNT = 5


@dataclass(frozen=True)
class ChunkSample:
    """One readable chunk selected from a Chroma collection."""

    collection: str
    chunk_id: str
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ChunkSampleResult:
    """Sampling summary and the selected chunks."""

    eligible_count: int
    samples: tuple[ChunkSample, ...]


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 Chroma 随机抽取切块并在控制台输出，供人工检查切块质量。"
    )
    parser.add_argument(
        "--count",
        type=positive_integer,
        default=DEFAULT_SAMPLE_COUNT,
        help=f"抽取数量，默认 {DEFAULT_SAMPLE_COUNT}。",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="随机种子；指定后可重复得到同一批样本。",
    )
    parser.add_argument(
        "--collection",
        help="只从指定 Chroma collection 抽样；默认遍历全部 collection。",
    )
    parser.add_argument(
        "--title",
        help="只抽取 metadata.title 完全匹配的切块，例如“电解器”。",
    )
    return parser


def _select_collections(client, collection_name: str | None):
    collections = list(client.list_collections())
    if collection_name is None:
        return collections

    selected = [
        collection
        for collection in collections
        if collection.name == collection_name
    ]
    if not selected:
        available = ", ".join(collection.name for collection in collections) or "无"
        raise ValueError(
            f"Chroma collection 不存在: {collection_name}；当前可用: {available}"
        )
    return selected


def sample_chunks(
    *,
    count: int = DEFAULT_SAMPLE_COUNT,
    seed: int,
    collection_name: str | None = None,
    title: str | None = None,
    client=None,
) -> ChunkSampleResult:
    """Sample chunk IDs first, then load only the selected documents.

    Chroma embeddings are intentionally excluded. This command is a read-only
    quality inspection tool and should not load the embedding model or mutate
    the vector database.
    """

    if count < 1:
        raise ValueError("count 必须大于 0")

    chroma_client = client or get_chroma_client()
    collections = _select_collections(chroma_client, collection_name)
    where = {"title": title.strip()} if title and title.strip() else None

    # 只加载 ID 来建立候选池，避免全量读取正文和向量。
    candidates: list[tuple[str, str]] = []
    collections_by_name = {}
    for collection in collections:
        collections_by_name[collection.name] = collection
        query: dict[str, Any] = {"include": []}
        if where is not None:
            query["where"] = where
        result = collection.get(**query)
        candidates.extend((collection.name, chunk_id) for chunk_id in result["ids"])

    if not candidates:
        return ChunkSampleResult(eligible_count=0, samples=())

    selected_refs = random.Random(seed).sample(
        candidates,
        k=min(count, len(candidates)),
    )
    ids_by_collection: dict[str, list[str]] = defaultdict(list)
    for selected_collection, chunk_id in selected_refs:
        ids_by_collection[selected_collection].append(chunk_id)

    # 按 collection 批量读取抽中的正文，再恢复随机抽样顺序。
    loaded: dict[tuple[str, str], ChunkSample] = {}
    for selected_collection, ids in ids_by_collection.items():
        result = collections_by_name[selected_collection].get(
            ids=ids,
            include=["documents", "metadatas"],
        )
        documents = result.get("documents") or [""] * len(result["ids"])
        metadatas = result.get("metadatas") or [{}] * len(result["ids"])
        for chunk_id, content, metadata in zip(
            result["ids"], documents, metadatas
        ):
            loaded[(selected_collection, chunk_id)] = ChunkSample(
                collection=selected_collection,
                chunk_id=chunk_id,
                content=content or "",
                metadata=metadata or {},
            )

    samples = tuple(loaded[reference] for reference in selected_refs)
    return ChunkSampleResult(
        eligible_count=len(candidates),
        samples=samples,
    )


def print_result(result: ChunkSampleResult, *, seed: int) -> None:
    print(f"Chroma 路径: {get_settings().chroma_db_path}")
    print(f"可抽样切块: {result.eligible_count}")
    print(f"实际抽取: {len(result.samples)}")
    print(f"随机种子: {seed}")

    if not result.samples:
        print("没有找到符合条件的切块。")
        return

    separator = "=" * 88
    for index, sample in enumerate(result.samples, start=1):
        print(f"\n{separator}")
        print(f"样本 {index}/{len(result.samples)}")
        print(f"Collection: {sample.collection}")
        print(f"Chunk ID: {sample.chunk_id}")
        print("元数据:")
        print(json.dumps(sample.metadata, ensure_ascii=False, indent=2, sort_keys=True))
        print("正文:")
        print(sample.content)
    print(f"\n{separator}")


def main() -> int:
    args = build_parser().parse_args()
    # 未指定种子时生成并打印一个种子，发现问题后可用它复现同一批样本。
    seed = args.seed
    if seed is None:
        seed = random.SystemRandom().randrange(0, 2**63)

    try:
        result = sample_chunks(
            count=args.count,
            seed=seed,
            collection_name=args.collection,
            title=args.title,
        )
        print_result(result, seed=seed)
        return 0 if result.samples else 1
    except Exception as exc:
        print(f"切块抽样失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
