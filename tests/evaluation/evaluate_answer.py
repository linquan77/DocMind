import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


REFUSAL_TEXT = "文档中未找到相关信息"


def load_dataset(path: Path):
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                yield json.loads(line)


def source_matches(actual_source: str, expected_sources):
    return any(expected in actual_source for expected in expected_sources)


def answer_has_keywords(answer: str, keywords):
    return all(keyword in answer for keyword in keywords)


def citation_ids(answer: str):
    return {int(value) for value in re.findall(r"\[(\d+)\]", answer)}


def evaluate(dataset_path: Path):
    from chain import get_qa_chain

    chain = get_qa_chain()
    rows = list(load_dataset(dataset_path))
    total = len(rows)
    answer_correct = 0
    citation_correct = 0
    refusal_correct = 0
    latencies = []
    total_tokens = []

    for row in rows:
        result = chain.invoke(row["question"])
        answer = result["answer"]
        sources = result.get("sources", [])
        latencies.append(result.get("latency_ms", 0))
        total_tokens.append(result.get("token_usage", {}).get("total_tokens", 0))

        should_refuse = row.get("should_refuse", False)
        did_refuse = bool(result.get("refused")) or answer.strip().startswith(REFUSAL_TEXT)
        if did_refuse == should_refuse:
            refusal_correct += 1

        if should_refuse:
            is_answer_correct = did_refuse
            is_citation_correct = did_refuse and not citation_ids(answer)
        else:
            is_answer_correct = answer_has_keywords(answer, row.get("expected_keywords", [])) and not did_refuse
            used_ids = citation_ids(answer)
            cited_sources = [
                doc.metadata.get("source", "")
                for doc in sources
                if doc.metadata.get("citation_id") in used_ids
            ]
            is_citation_correct = bool(used_ids) and any(
                source_matches(source, row.get("expected_sources", []))
                for source in cited_sources
            )

        answer_correct += 1 if is_answer_correct else 0
        citation_correct += 1 if is_citation_correct else 0

        print(json.dumps({
            "id": row["id"],
            "answer": answer,
            "rewritten_query": result.get("rewritten_query"),
            "latency_ms": result.get("latency_ms"),
            "refused": did_refuse,
            "token_usage": result.get("token_usage", {}),
            "answer_correct": is_answer_correct,
            "citation_correct": is_citation_correct,
            "sources": [
                {
                    "citation_id": doc.metadata.get("citation_id"),
                    "source": doc.metadata.get("source"),
                    "score": round(doc.metadata.get("score", 0), 4),
                }
                for doc in sources
            ],
        }, ensure_ascii=False))

    metrics = {
        "answer_accuracy": answer_correct / total if total else 0,
        "citation_accuracy": citation_correct / total if total else 0,
        "refusal_accuracy": refusal_correct / total if total else 0,
        "average_latency_ms": sum(latencies) / total if total else 0,
        "average_total_tokens": sum(total_tokens) / total if total else 0,
        "count": total,
    }
    print("\nMETRICS")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate answer quality for the RAG project.")
    parser.add_argument("--dataset", default=PROJECT_ROOT / "tests/evaluation/dataset.jsonl", type=Path)
    parser.add_argument("--no-reranker", action="store_true", help="Disable reranker for a faster baseline run.")
    parser.add_argument("--no-query-rewrite", action="store_true", help="Disable query rewrite for a faster baseline run.")
    args = parser.parse_args()
    if args.no_reranker:
        os.environ["ENABLE_RERANKER"] = "false"
    if args.no_query_rewrite:
        os.environ["ENABLE_QUERY_REWRITE"] = "false"
    evaluate(args.dataset)
