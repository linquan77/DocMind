# DocMind

DocMind 是一个正在工程化改造中的 RAG 知识库问答项目。当前主入口是 FastAPI，支持本地文档管理、独立检索、基于证据的问答，以及《缺氧》中文 Wiki 的增量同步和版本化向量索引。

## 当前状态

已经实现：

- FastAPI 异步接口、Pydantic 请求响应模型和统一异常结构
- CORS、结构化日志和 `X-Trace-ID`
- PDF、DOCX、XLSX、HTML 本地文件解析
- SQLite 文档/Wiki 元数据与 Alembic 迁移
- Chroma 向量存储和按 `document_id` 删除
- BM25 + 向量混合检索、Reranker、Metadata 过滤
- 查询改写、上下文 token 预算、来源引用和无证据拒答
- 服务端权限过滤边界，尚未接入实际登录系统
- 《缺氧》中文 Wiki 分类发现、增量对比、dry-run 和原始快照
- Wiki 信息框/章节解析、结构化切块和版本化 Chroma 索引
- Pytest 单元与接口测试

尚未实现：

- React + TypeScript + Vite 前端
- 会话持久化和 `GET /sessions/{id}`
- Wiki 全量数据质量报告
- 面向 Agent 的工具协议；当前只保留了可独立调用的检索边界
- FastAPI 容器化改造和部署配置

仓库仍保留第一阶段的 Streamlit 入口 `app.py`。现有 `Dockerfile` 和 `docker-compose.yml` 也仍然启动旧 Streamlit 应用，不是当前 FastAPI 服务的推荐启动方式。

## 项目结构

```text
app/
├── api/          # FastAPI 路由
├── commands/     # Wiki 同步、索引等命令行入口
├── core/         # 配置、数据库、日志、异常和权限边界
├── models/       # SQLAlchemy 数据模型
├── rag/          # 解析、切块、向量化、检索、重排和生成
├── schemas/      # Pydantic 请求响应模型
├── services/     # 业务流程编排
└── main.py       # FastAPI 应用入口

migrations/       # Alembic 数据库迁移
tests/            # 单元测试、API 测试和第一阶段评测
docs/             # 数据库结构及历史说明
data/raw/wiki/    # Wiki 原始快照，本地生成且不提交 Git
chroma_db/        # Chroma 本地数据，不提交 Git
```

## 技术栈

- FastAPI、Pydantic、Uvicorn
- SQLAlchemy、Alembic、SQLite
- LangChain、Chroma
- BGE 中文 Embedding、可选 BGE Reranker
- DeepSeek 兼容的 OpenAI API
- Pytest

模型名称和 API 地址通过环境变量配置，不在代码中绑定某个固定的 DeepSeek 版本。

## 本地启动

建议使用 Python 3.11。

```bash
git clone https://github.com/linquan77/DocMind.git
cd DocMind

python -m venv .venv
```

激活虚拟环境：

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

安装依赖并创建本地配置：

```bash
pip install -r requirements.txt

# Windows PowerShell
Copy-Item .env.example .env

# macOS / Linux
cp .env.example .env
```

编辑 `.env`，至少填写可用的 `DEEPSEEK_API_KEY`，并按实际服务设置 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`。

初始化或升级数据库：

```bash
python -m alembic upgrade head
```

启动 FastAPI：

```bash
uvicorn app.main:app --reload
```

启动后可访问：

- OpenAPI/Swagger：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

`/health` 返回机器可读的 JSON 状态，不是面向用户的前端页面。

## 环境变量

完整示例见 `.env.example`，常用配置包括：

| 变量 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 大模型 API Key |
| `DEEPSEEK_BASE_URL` | OpenAI 兼容 API 地址 |
| `DEEPSEEK_MODEL` | 查询改写与回答模型 |
| `DATABASE_URL` | SQLite 或其他 SQLAlchemy 数据库地址 |
| `CHROMA_DB_PATH` | Chroma 持久化目录 |
| `MODEL_CACHE_PATH` | Embedding/Reranker 模型缓存目录 |
| `CORS_ORIGINS` | 允许访问 API 的前端来源，逗号分隔 |
| `CHUNK_SIZE` | 普通文档和 Wiki 长章节的切块长度 |
| `CHUNK_OVERLAP` | 切块重叠长度 |
| `ENABLE_RERANKER` | 是否启用重排序模型 |
| `ENABLE_QUERY_REWRITE` | 是否启用查询改写 |

## API

当前实际提供以下接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/documents` | 上传并索引本地文档 |
| `GET` | `/documents` | 分页查询文档元数据 |
| `DELETE` | `/documents/{id}` | 删除 SQLite 元数据和 Chroma 切块 |
| `POST` | `/search` | 独立检索，不调用回答模型 |
| `POST` | `/chat` | 基于检索证据回答问题 |
| `GET` | `/health` | 服务健康检查 |

### 上传文档

稳定支持 `.pdf`、`.docx`、`.xlsx`、`.html` 和 `.htm`。旧式 `.xls` 请先转换为 `.xlsx`；HTML 只解析文件中已有的内容，不执行 JavaScript，也不会递归抓取链接。

```bash
curl -X POST http://127.0.0.1:8000/documents \
  -F "file=@docs/example.pdf"
```

### 查询文档

```bash
curl "http://127.0.0.1:8000/documents?offset=0&limit=50"
```

### 删除文档

```bash
curl -X DELETE http://127.0.0.1:8000/documents/{document_id}
```

### 独立检索

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"电解器每秒产生多少氧气？","top_k":10}'
```

`document_ids` 是可选的用户选择范围；服务端仍会与可信授权范围取交集，客户端参数不能扩大权限。

### 文档问答

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"电解器每秒产生多少氧气？","top_k":4}'
```

响应包含改写后的查询、引用来源、向量/BM25/Rerank 分数、token 用量、上下文估算 token 数和截断状态。

## 独立调用检索器

检索模块不依赖问答接口，可以被测试代码、后台任务或未来的 Agent 直接调用：

```python
from app.rag.retriever import get_retriever

retriever = get_retriever()
results = retriever.search("电解器如何制氧？", top_k=10)
```

## 《缺氧》中文 Wiki 数据流程

数据来源：`https://oxygennotincluded.wiki.gg/zh/`

当前同步范围是正文命名空间中的“建筑”和“小动物”分类及其子分类，并排除调试、未实装、未使用、已移除等内容。项目仅用于学习和非商业演示。

Wiki 数据分为三层：

```text
MediaWiki API
    ↓
data/raw/wiki/{page_id}/{revision_id}.json   原始不可变快照
    ↓
信息框/正文解析 → 按章节切块
    ↓
chroma_db/                                  切块与向量

SQLite                                      页面、修订和索引状态
```

原始 JSON 会保留 Wikitext 和 HTML，不能直接作为向量切块。索引命令只会把清洗后的信息框和正文 `WikiSection` 写入 Chroma。

### 1. 查看同步计划

```bash
python -m app.commands.sync_wiki --dry-run
```

`--dry-run` 只访问 Wiki API 并输出新增、更新、未变化和下线计划，不写 SQLite 或快照。

### 2. 同步原始快照

完整同步：

```bash
python -m app.commands.sync_wiki
```

只同步指定页面：

```bash
python -m app.commands.sync_wiki \
  --title "电解器" \
  --title "人力发电机" \
  --title "好吃哈奇"
```

指定 `--title` 时属于部分同步，不会把其他页面误判为下线。只有完整同步可以检测远端下线页面并更新数据源的完整同步时间。

同步命令只保存 SQLite 元数据和原始快照，将页面标记为 `pending_index`，不会写入 Chroma。

### 3. 查看索引计划

```bash
python -m app.commands.index_wiki --dry-run --verbose
```

### 4. 写入 Chroma

索引全部待处理页面：

```bash
python -m app.commands.index_wiki
```

索引指定页面：

```bash
python -m app.commands.index_wiki \
  --title "电解器" \
  --title "人力发电机" \
  --title "好吃哈奇"
```

可以使用 `--limit N` 限制单次索引页数。

Wiki 切块 ID 格式为：

```text
wiki:{page_id}:{revision_id}:{chunk_index}
```

页面出现新修订时，索引流程会先写入并校验新版本，成功后再删除旧版本。失败时保留旧 `indexed_revision_id` 并将文档标记为 `index_failed`；重复执行已经是最新版本的页面会直接跳过。

## 数据存储职责

| 存储 | 内容 | 是否提交 Git |
| --- | --- | --- |
| SQLite（默认 `docmind.db`） | 文档目录、状态、Wiki 页面和修订信息 | 否 |
| `data/raw/wiki/` | 按页面和修订保存的原始 Wiki JSON | 否 |
| `chroma_db/` | 普通文档和 Wiki 的切块、元数据与向量 | 否 |
| `models/` | Embedding/Reranker 模型缓存 | 否 |
| `docs/database-schema.md` | 数据库结构说明 | 是 |

## 测试

运行全部测试：

```bash
python -m pytest -q
```

Wiki 测试覆盖增量对比、只读 dry-run、不可变快照、不同页面结构解析、章节切块、版本化向量替换、失败回滚和索引幂等。

第一阶段检索与回答评测仍保留在 `tests/evaluation/`：

```bash
python tests/evaluation/evaluate_retrieval.py --top-k 5
python tests/evaluation/evaluate_answer.py
```

数据库结构说明见 `docs/database-schema.md`，历史改造记录见 `docs/version_updates.md`。
