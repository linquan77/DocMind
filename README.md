# RAG 知识库问答系统

基于 LangChain + DeepSeek V4 + Chroma 的多格式文档智能问答系统。
AI-powered document Q&A system based on RAG, LangChain & DeepSeek

## 功能
- 支持 PDF、Word、Excel 和本地 HTML 文档解析
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

## 第二阶段：FastAPI 服务

当前已加入 FastAPI 服务、文档管理、独立检索和问答接口。SQLite 保存文档元数据，Chroma 继续保存文档切块及向量。

启动 API：

```bash
uvicorn app.main:app --reload
```

接口文档：`http://127.0.0.1:8000/docs`

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

上传文档：

```bash
curl -X POST http://127.0.0.1:8000/documents \
  -F "file=@docs/example.pdf"
```

第一版 HTML 支持本地 `.html` 和 `.htm` 文件，提取文件中已有的可见文本，不执行 JavaScript，也不会抓取链接页面：

```bash
curl -X POST http://127.0.0.1:8000/documents \
  -F "file=@docs/example.html"
```

查看文档元数据：

```bash
curl http://127.0.0.1:8000/documents
```

删除文档：

```bash
curl -X DELETE http://127.0.0.1:8000/documents/{document_id}
```

独立检索（不会调用大模型）：

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"文档讲了什么？","top_k":10}'
```

文档问答：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"文档讲了什么？","top_k":4}'
```

检索器也可以被未来的 Agent 直接调用：

```python
from app.rag.retriever import get_retriever

retriever = get_retriever()
results = retriever.search("文档讲了什么？", top_k=10)
```

每个检索结果保留来源、页码、向量分数、BM25 分数、Rerank 分数和排序说明。`/chat` 额外返回模型 token 用量、上下文估算 token 数及是否发生上下文截断。

检索层已经预留服务端权限范围：用户选择的文档集合会与授权系统提供的文档集合取交集。当前版本尚未接入登录系统，因此默认授权依赖返回无限制；接入认证后只需替换 `app/core/security.py` 中的依赖。

## 缺氧中文 Wiki 增量同步

先升级数据库：

```bash
python -m alembic upgrade head
```

只读取远端分类和修订信息、查看同步计划，不写数据库和文件：

```bash
python -m app.commands.sync_wiki --dry-run
```

需要查看每个页面的计划时加入 `--verbose`。确认计划后，执行正式快照同步：

```bash
python -m app.commands.sync_wiki
```

正式同步只保存 SQLite 元数据和 `data/raw/wiki/{page_id}/{revision_id}.json` 原始快照，并将文档标记为 `pending_index`；当前阶段不会解析页面或写入 Chroma。

开发阶段可以用可重复的 `--title` 参数只验证少量页面：

```bash
python -m app.commands.sync_wiki --dry-run --verbose --title "电解器" --title "人力发电机" --title "好吃哈奇"
python -m app.commands.sync_wiki --title "电解器" --title "人力发电机" --title "好吃哈奇"
```

指定 `--title` 时属于部分同步：页面必须位于允许的“建筑/小动物”分类范围内，并且不会把未指定页面误判为下线。只有不指定标题的完整同步才会检测远端已删除页面并更新数据源的完整同步时间。
