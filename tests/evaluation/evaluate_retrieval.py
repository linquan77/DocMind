import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def load_dataset(path: Path):
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                yield json.loads(line)


def source_matches(actual_source: str, expected_sources):
    return any(expected in actual_source for expected in expected_sources)


def evaluate(dataset_path: Path, top_k: int):
    from retriever import get_retriever

    retriever = get_retriever()
    rows = list(load_dataset(dataset_path))
    total = len(rows)
    evidence_rows = [row for row in rows if not row.get("should_refuse")]
    recall_hits = 0
    reciprocal_ranks = []
    latencies = []

    for row in rows:
        started = time.perf_counter()
        results = retriever.retrieve(row["question"], top_k=top_k)
        latencies.append((time.perf_counter() - started) * 1000)

        expected_sources = row.get("expected_sources", [])
        if not row.get("should_refuse"):
            hit_rank = next(
                (
                    index
                    for index, item in enumerate(results, start=1)
                    if source_matches(item.doc.metadata.get("source", ""), expected_sources)
                ),
                None,
            )
        else:
            hit_rank = None

        if not row.get("should_refuse"):
            recall_hits += 1 if hit_rank and hit_rank <= top_k else 0
            reciprocal_ranks.append(1 / hit_rank if hit_rank else 0.0)

        print(json.dumps({
            "id": row["id"],
            "top_sources": [
                {
                    "source": item.doc.metadata.get("source"),
                    "score": round(item.score, 4),
                    "rank_reason": item.rank_reason,
                }
                for item in results
            ],
            "hit_rank": hit_rank,
        }, ensure_ascii=False))

    evidence_count = len(evidence_rows)
    metrics = {
        f"Recall@{top_k}": recall_hits / evidence_count if evidence_count else 0,
        "MRR": sum(reciprocal_ranks) / evidence_count if evidence_count else 0,
        "average_latency_ms": sum(latencies) / total if total else 0,
        "count": total,
        "evidence_count": evidence_count,
    }
    print("\nMETRICS")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality for the RAG project.")
    parser.add_argument("--dataset", default=PROJECT_ROOT / "tests/evaluation/dataset.jsonl", type=Path)
    parser.add_argument("--top-k", default=5, type=int)
    parser.add_argument("--no-reranker", action="store_true", help="Disable reranker for a faster baseline run.")
    args = parser.parse_args()
    if args.no_reranker:
        os.environ["ENABLE_RERANKER"] = "false"
    evaluate(args.dataset, args.top_k)
