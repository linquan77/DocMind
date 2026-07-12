# RAG 知识库问答系统

基于 LangChain + DeepSeek V4 + Chroma 的多格式文档智能问答系统。
AI-powered document Q&A system based on RAG, LangChain & DeepSeek

## 功能
- 支持 PDF、Word、网页文档解析
- 支持 BM25 + 向量混合检索
- 支持 Reranker 重排序、相似度阈值过滤
- 支持 Metadata 过滤和前端文档选择
- 支持查询改写、引用编号、无证据拒答
- DeepSeek V4 生成回答，支持流式输出
- 来源引用展示

## 快速开始

1. 克隆项目
```bash
git clone https://github.com/linquan77/Docmind.git
cd Docmind
```

2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填入你的 DeepSeek API Key
```

3. 启动
```bash
docker compose up --build
```

4. 打开浏览器访问 `http://localhost:8501`

## 技术栈
- LangChain
- DeepSeek V4 API
- Chroma 向量数据库
- Streamlit

## 第一阶段评测

评测集位于 `tests/evaluation/`：

```bash
python tests/evaluation/evaluate_retrieval.py --top-k 5
python tests/evaluation/evaluate_answer.py
```

评测指标包括 `Recall@5`、`MRR`、答案正确率、引用正确率、拒答准确率和平均延迟。

详细版本说明见 `docs/version_updates.md`。
