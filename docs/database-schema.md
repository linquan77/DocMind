# DocMind 数据库结构

本文档记录第二阶段当前使用的数据存储及表结构。数据库版本由 Alembic 管理，结构发生变更时必须新增迁移并同步更新本文档。

## 存储职责

DocMind 当前使用两类本地存储：

| 存储 | 默认位置 | 职责 |
| --- | --- | --- |
| SQLite | `./docmind.db` | 保存文档、Wiki 来源、页面修订和同步任务状态 |
| Chroma | `./chroma_db` | 保存文档切块、向量和切块元数据 |
| 原始快照 | `./data/raw/wiki` | 保存 Wiki 原始 wikitext、HTML 和修订信息，不提交 Git |

SQLite 是文档目录信息的来源，Chroma 中的切块通过 `document_id` 与 SQLite 文档关联。两者目前不能共享事务，删除流程采用“先删 Chroma、成功后再删 SQLite”的顺序，并在向量删除失败时恢复文档状态。

## SQLite 表

### `documents`

对应模型：`app/models/document.py` 中的 `DocumentRecord`。

| 字段 | SQLite 类型 | 可为空 | 说明 |
| --- | --- | --- | --- |
| `id` | `VARCHAR(36)` | 否 | 主键，UUID 字符串；同时写入 Chroma 切块元数据 |
| `filename` | `VARCHAR(512)` | 否 | 上传时的原始文件名 |
| `content_type` | `VARCHAR(255)` | 是 | 文件 MIME 类型 |
| `size_bytes` | `INTEGER` | 否 | 原始文件字节数 |
| `status` | `VARCHAR(32)` | 否 | 生命周期状态，当前使用 `processing`、`pending_index`、`indexing`、`ready`、`failed`、`index_failed`、`deleting`、`source_removed` |
| `chunk_count` | `INTEGER` | 否 | 成功写入 Chroma 的切块数量 |
| `error_message` | `TEXT` | 是 | 文档处理或删除失败时的说明 |
| `created_at` | `DATETIME` | 否 | 创建时间，按 UTC 写入 |
| `updated_at` | `DATETIME` | 否 | 最近更新时间，按 UTC 写入 |

索引：

- 主键索引：`id`
- 普通索引：`filename`
- 普通索引：`status`

### `wiki_sources`

记录可同步的 MediaWiki 站点和抓取策略。第一版对应中文缺氧 Wiki。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `VARCHAR(36)` | 主键 |
| `name` | `VARCHAR(255)` | 数据源名称 |
| `api_url` | `VARCHAR(1024)` | MediaWiki API 地址，全局唯一 |
| `base_url` | `VARCHAR(1024)` | 页面基础地址 |
| `language` | `VARCHAR(32)` | 站点语言，当前为 `zh` |
| `root_categories_json` | `TEXT` | 根分类 JSON，当前为建筑和小动物 |
| `excluded_category_keywords_json` | `TEXT` | 排除分类关键词 JSON |
| `license_name` | `VARCHAR(255)` | 内容许可名称 |
| `license_url` | `VARCHAR(1024)` | 内容许可链接 |
| `status` | `VARCHAR(32)` | 来源状态，如 `active`、`disabled` |
| `last_synced_at` | `DATETIME` | 最近一次成功同步时间 |
| `created_at` | `DATETIME` | 创建时间 |
| `updated_at` | `DATETIME` | 更新时间 |

### `wiki_pages`

记录 Wiki 页面与 `documents` 的一对一关系，是增量同步判断的核心。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `VARCHAR(36)` | 主键 |
| `document_id` | `VARCHAR(36)` | 外键，关联 `documents.id`，删除文档时级联删除 |
| `source_id` | `VARCHAR(36)` | 外键，关联 `wiki_sources.id` |
| `page_id` | `INTEGER` | MediaWiki 页面稳定 ID |
| `revision_id` | `INTEGER` | 最近已保存为原始快照的 Wiki 修订 ID |
| `indexed_revision_id` | `INTEGER` | Chroma 当前使用的修订 ID；为空表示等待解析和索引 |
| `title` | `VARCHAR(512)` | 页面标题 |
| `canonical_url` | `VARCHAR(1024)` | 页面规范 URL |
| `namespace` | `INTEGER` | MediaWiki namespace，第一版只接受 0 |
| `categories_json` | `TEXT` | 页面所属抓取分类 JSON |
| `content_sha256` | `VARCHAR(64)` | 原始内容摘要，用于额外去重和完整性检查 |
| `snapshot_path` | `VARCHAR(1024)` | 原始快照相对路径 |
| `source_updated_at` | `DATETIME` | Wiki 修订时间 |
| `synced_at` | `DATETIME` | 本地同步时间 |

唯一约束：`(source_id, page_id)`；同一个 Wiki 页面不会重复创建文档。

### `wiki_sync_runs`

每执行一次同步就记录一行，用于日志追踪、失败诊断和后续管理后台展示。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `VARCHAR(36)` | 主键 |
| `source_id` | `VARCHAR(36)` | 外键，关联 `wiki_sources.id` |
| `scope` | `VARCHAR(32)` | `full` 或 `partial`；只有完整同步可以判断页面下线 |
| `requested_titles_json` | `TEXT` | 部分同步请求的页面标题 JSON |
| `status` | `VARCHAR(32)` | `running`、`completed`、`completed_with_errors` 或 `failed` |
| `discovered_count` | `INTEGER` | 分类遍历发现的页面数 |
| `created_count` | `INTEGER` | 新增页面数 |
| `updated_count` | `INTEGER` | 修订发生变化的页面数 |
| `removed_count` | `INTEGER` | 已离开抓取范围并标记为 `source_removed` 的页面数 |
| `unchanged_count` | `INTEGER` | revision_id 未变化、直接跳过的页面数 |
| `failed_count` | `INTEGER` | 处理失败页面数 |
| `error_message` | `TEXT` | 同步级错误信息 |
| `started_at` | `DATETIME` | 开始时间 |
| `completed_at` | `DATETIME` | 完成或失败时间 |

`GET /sessions/{id}` 所需的 `sessions` 和 `messages` 表尚未实现；它们会在 Wiki 同步和检索评测稳定后通过新的 Alembic 迁移加入。

## Chroma 数据结构

默认 collection 名称为 `langchain`。Chroma 不使用固定关系表结构，每个切块包含正文、向量和 metadata。当前关键 metadata 包括：

| metadata | 说明 |
| --- | --- |
| `document_id` | 对应 `documents.id`，用于权限过滤和整篇文档删除 |
| `source` | 原始文件名或来源标识 |
| `type` | 文档类型，例如 `pdf`、`docx`、`xlsx`、`html` |
| `page` | PDF 等分页文档的页码（适用时） |
| `row` | Excel 数据所在行（适用时） |
| `chunk_index` | 文档内部的切块序号 |
| `title` | HTML 等文档提取出的标题（适用时） |
| `wiki_page_id` | MediaWiki 页面 ID（Wiki 数据适用） |
| `wiki_revision_id` | MediaWiki 修订 ID（Wiki 数据适用） |
| `wiki_url` | 原始页面地址（Wiki 数据适用） |
| `categories` | 页面所属抓取分类（Wiki 数据适用） |

检索时产生的向量分数、BM25 分数和 rerank 分数属于运行时评测数据，目前随 API 响应返回，不持久化到 SQLite。

## 配置项

可通过环境变量覆盖默认路径：

```ini
DATABASE_URL=sqlite:///./docmind.db
CHROMA_DB_PATH=./chroma_db
MEDIAWIKI_API_URL=https://oxygennotincluded.wiki.gg/zh/api.php
MEDIAWIKI_SNAPSHOT_PATH=./data/raw/wiki
```

执行迁移：

```bash
python -m alembic upgrade head
```

生产环境切换 PostgreSQL 时，应保持 API Schema 不变，并继续通过 Alembic 管理结构。
