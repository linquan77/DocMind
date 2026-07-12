# RAG 第一阶段评测报告

本目录用于持续评估 RAG 系统质量。每次修改检索、切块、提示词、Reranker 或阈值后，都建议重新运行评测并把结果记录到这里。

## 数据集

- `dataset.jsonl`：每行是一条评测样本。
- 字段说明：
  - `id`：样本编号。
  - `question`：用户问题。
  - `expected_sources`：期望命中的来源文件名，可以写多个候选来源。
  - `expected_keywords`：答案中应该包含的关键词。
  - `should_refuse`：证据不足时是否应该拒答。

## 运行命令

```bash
python tests/evaluation/evaluate_retrieval.py --top-k 5
python tests/evaluation/evaluate_answer.py
```

快速基线可以先关闭耗时能力：

```bash
python tests/evaluation/evaluate_retrieval.py --top-k 5 --no-reranker
python tests/evaluation/evaluate_answer.py --no-reranker --no-query-rewrite
```

## 指标

- `Recall@5`：只统计有证据问题，前 5 个检索结果中是否至少有一个正确来源。它衡量“有没有把证据找回来”。
- `MRR`：只统计有证据问题，正确来源排名越靠前分数越高。它衡量“正确证据是不是排在前面”。
- `answer_accuracy`：答案是否包含期望关键词，且不该拒答时没有拒答。
- `citation_accuracy`：答案是否使用了引用编号，并且引用编号对应的来源是正确来源。
- `refusal_accuracy`：该拒答时拒答，不该拒答时不拒答。
- `average_latency_ms`：平均耗时，单位毫秒。

## 当前基线

运行时间：2026-07-10

快速基线命令：

```bash
python tests/evaluation/evaluate_retrieval.py --top-k 5 --no-reranker
python tests/evaluation/evaluate_answer.py --no-reranker --no-query-rewrite
```

检索指标：

```json
{
  "Recall@5": 1.0,
  "MRR": 0.8333333333333334,
  "average_latency_ms": 1877.3132750065997,
  "count": 4,
  "evidence_count": 3
}
```

回答指标：

```json
{
  "answer_accuracy": 1.0,
  "citation_accuracy": 1.0,
  "refusal_accuracy": 1.0,
  "average_latency_ms": 3838.75,
  "count": 4
}
```

说明：这是关闭 Reranker 和查询改写后的快速基线，适合日常开发时快速检查系统是否退化。开启 Reranker 后通常会提升排序质量，但本机首次加载耗时明显更高，建议单独评测。

## 如何解读

- `Recall@5` 低：优先检查文档是否入库、切块是否太大或太小、BM25 分词是否覆盖关键词。
- `MRR` 低但 `Recall@5` 高：说明证据找到了但排序不好，优先调 `VECTOR_WEIGHT`、`BM25_WEIGHT`、`RERANKER_SCORE_THRESHOLD` 或 Reranker 模型。
- `answer_accuracy` 低：检查提示词是否过严、上下文是否缺失、问题是否需要查询改写。
- `citation_accuracy` 低：检查答案提示词和引用编号格式，确认模型没有使用不存在的编号。
- `refusal_accuracy` 低：检查相似度阈值是否太低，以及提示词是否明确禁止无证据猜测。
- `average_latency_ms` 高：优先关闭查询改写或 Reranker 做对比，再决定是否换更小模型或减少候选数量。
