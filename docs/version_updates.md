# 版本更新文档

## 第一阶段：高质量 RAG 基础能力升级

本阶段目标是把原来的“纯向量检索 + 大模型回答”升级成更可靠、更可评估的 RAG 系统。重点能力包括：BM25 + 向量混合检索、Reranker、相似度阈值、Metadata 过滤、文档选择、查询改写、引用编号、无证据拒答，以及评测集。

### 1. BM25 + 向量混合检索

修改文件：`retriever.py`

做了什么：
- 新增 `HybridRetriever`，替代原来的单一 Chroma retriever。
- 同时执行两种召回：
  - 向量检索：适合找语义相近的内容。
  - BM25 检索：适合找关键词、专有名词、编号、商品名、价格等精确匹配内容。
- 将两路分数归一化后按权重融合。

为什么要这么改：
- 纯向量检索容易漏掉精确词，比如商品名、型号、文件里的固定表达。
- 纯 BM25 又不理解语义相似，比如“多少钱”和“单价”是相近意思。
- 混合检索能同时照顾“语义理解”和“关键词命中”，是高质量 RAG 的常见基础配置。

可调参数：`config.py`
- `VECTOR_TOP_K`：向量检索先召回多少个候选块。
- `BM25_TOP_K`：BM25 先召回多少个候选块。
- `VECTOR_WEIGHT`：向量分数权重。
- `BM25_WEIGHT`：BM25 分数权重。

### 2. Reranker 重排序

修改文件：`retriever.py`、`config.py`

做了什么：
- 新增 Reranker 步骤，对混合检索召回的候选块重新排序。
- 默认使用 `BAAI/bge-reranker-base`。
- 如果模型加载失败，会自动退回到混合检索分数，避免整个系统不可用。

为什么要这么改：
- 第一阶段召回是“尽量多找回来”，但找回来的内容不一定排序最好。
- Reranker 会逐条判断“问题和证据块是否真的相关”，通常能把真正有用的证据排到前面。
- 对 RAG 来说，排在前面的上下文会更影响最终答案，所以重排序很重要。

可调参数：`config.py`
- `ENABLE_RERANKER`：是否启用 Reranker。
- `RERANKER_MODEL`：Reranker 模型名。
- `RERANKER_CANDIDATE_K`：送入 Reranker 的候选数量。
- `RERANKER_WEIGHT`：Reranker 分数在最终排序中的权重。

### 3. 相似度阈值

修改文件：`retriever.py`、`config.py`

做了什么：
- 新增 `RERANKER_SCORE_THRESHOLD`。
- 排序完成后，低于阈值的证据块会被过滤掉。
- 如果没有任何证据块通过阈值，系统会直接拒答。

为什么要这么改：
- RAG 最大风险之一是“明明没找到证据，大模型却硬答”。
- 阈值相当于一道质量门槛：相关度太低的内容不进入回答阶段。
- 阈值越高，越保守；阈值越低，召回更多但误答风险更高。

### 4. Metadata 过滤

修改文件：`retriever.py`、`chain.py`、`app.py`

做了什么：
- 检索函数支持 `metadata_filter`。
- 当前界面主要使用 `source` 字段过滤，也就是只在指定文档中检索。
- 底层也支持简单等值过滤和 `$in` 多值过滤。

为什么要这么改：
- 用户有时只想问某一份文档，不希望系统从整个知识库里混合找答案。
- Metadata 过滤能减少无关候选，提高准确率，也能降低延迟。
- 以后可以继续扩展到 `type`、`page`、`row`、`chunk_index` 等字段。

### 5. 文档选择

修改文件：`app.py`

做了什么：
- 在侧边栏新增“文档选择”多选框。
- 默认选择全部文档。
- 如果用户只选择部分文档，问答只会在这些文档中检索。

为什么要这么改：
- 初学者最容易遇到的问题是“知识库里文档多了以后，答案串文档”。
- 文档选择能让用户明确限定检索范围，是最直观的 metadata 过滤入口。

### 6. 查询改写

修改文件：`chain.py`、`config.py`

做了什么：
- 在检索前增加查询改写。
- 大模型会把用户问题改写成更适合检索的独立查询。
- 如果改写失败，会自动使用原问题。

为什么要这么改：
- 用户提问常常很口语化，比如“这个多少钱”“它有什么特点”。
- 检索系统更喜欢清晰、完整、包含关键词的问题。
- 查询改写可以补全表达，提高召回率。

可调参数：`config.py`
- `ENABLE_QUERY_REWRITE`：是否启用查询改写。

### 7. 引用编号

修改文件：`chain.py`、`app.py`

做了什么：
- 检索结果会被格式化成 `[1]`、`[2]`、`[3]` 这样的证据编号。
- 提示词要求模型每个关键结论后都带引用编号。
- 前端来源区域也显示相同编号，方便用户核对。

为什么要这么改：
- 高质量 RAG 不只要回答，还要告诉用户“答案来自哪里”。
- 引用编号让答案可以追溯，用户能判断模型有没有依据。
- 后续评测也可以检查引用是否正确。

### 8. 无证据拒答

修改文件：`chain.py`

做了什么：
- 如果没有检索到超过阈值的证据，直接返回：`文档中未找到相关信息。`
- 提示词也要求证据不足时必须拒答，不能编造。

为什么要这么改：
- RAG 的核心原则是“基于证据回答”。
- 当证据不足时，诚实拒答比生成一个看似合理但没有依据的答案更可靠。
- 这也是后续上线前必须重点评估的能力。

### 9. 入库 Metadata 增强

修改文件：`ingest.py`

做了什么：
- 给每个切块新增：
  - `chunk_index`：当前切块编号。
  - `chunk_total`：该文档总切块数。

为什么要这么改：
- 这些字段能帮助定位证据块在文档中的大致位置。
- 评测和调试时可以知道系统命中的是第几个切块。
- 以后做上下文扩展、相邻切块补充时也会用到。

### 10. 评测集

新增目录：`tests/evaluation/`

新增文件：
- `dataset.jsonl`
- `evaluate_retrieval.py`
- `evaluate_answer.py`
- `report.md`

做了什么：
- `dataset.jsonl` 保存评测样本。
- `evaluate_retrieval.py` 评估检索效果。
- `evaluate_answer.py` 评估端到端回答效果。
- `report.md` 记录指标说明、运行方式和后续基线。
- 评测脚本支持 `--no-reranker` 和 `--no-query-rewrite`，方便先跑快速基线，再逐项打开增强能力做对比。

为什么要这么改：
- 没有评测就不知道修改到底是变好还是变差。
- RAG 系统非常依赖参数，必须用固定样本反复比较。
- 第一阶段至少评估以下指标：
  - `Recall@5`
  - `MRR`
  - 答案正确率
  - 引用正确率
  - 拒答准确率
  - 平均延迟

运行方式：

```bash
python tests/evaluation/evaluate_retrieval.py --top-k 5
python tests/evaluation/evaluate_answer.py
python tests/evaluation/evaluate_retrieval.py --top-k 5 --no-reranker
python tests/evaluation/evaluate_answer.py --no-reranker --no-query-rewrite
```

### 11. 前端展示优化

修改文件：`app.py`

做了什么：
- 回答后显示改写后的查询。
- 显示本次问答延迟。
- 来源区域显示引用编号、相关度分数和排序原因。
- 删除了原文件末尾重复追加 assistant 消息的代码。

为什么要这么改：
- 初学 RAG 时，需要看到系统内部发生了什么。
- 改写查询、相关度、排序原因能帮助判断问题出在检索、排序还是生成。
- 修复重复追加消息可以避免聊天记录出现异常。

### 12. 依赖版本兼容

修改文件：`requirements.txt`、`config.py`、`retriever.py`、`.env.example`

做了什么：
- 将 `torch==2.3.0+cpu` 调整为 `torch>=2.6.0`。
- 将 `transformers==4.44.0` 调整为 `transformers>=4.56.0`。
- 新增 `MODEL_CACHE_PATH=./models`，并让 Embedding 与 Reranker 模型缓存写入项目内的 `models/` 目录。

为什么要这么改：
- 当前 Python 3.13 环境中没有可用的 `torch==2.3.0+cpu` 安装包。
- 固定过旧版本会导致新环境无法安装依赖，项目还没运行就失败。
- `transformers==4.44.0` 依赖的旧 `tokenizers` 在 Python 3.13 Windows 环境中没有现成 wheel，会尝试本地编译并要求 Visual C++ Build Tools。
- 默认 HuggingFace 缓存目录在用户目录下，受限环境可能没有写权限；放到项目 `models/` 目录更容易管理，也不会被 Git 提交。
- 放宽版本后，pip 可以选择与当前 Python 版本兼容的 Torch 和 Tokenizers 包。
