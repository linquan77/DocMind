# Wiki 数据处理技术文档

本文描述 DocMind 当前《缺氧》中文 Wiki 数据管线的真实实现，包括页面发现、增量同步、原始快照、HTML 解析、语义切块、向量索引和质量抽查。规划中但尚未实现的能力会明确标注。

## 1. 目标与范围

第一版数据源为《缺氧》中文 Wiki：

- API：`https://oxygennotincluded.wiki.gg/zh/api.php`
- 页面范围：正文命名空间。
- 根分类：建筑、小动物。
- 分类发现：递归遍历子分类。
- 排除范围：调试、未实装、未使用、已移除、开发者等关键词。
- 使用场景：学习和非商业演示。

当前流程优先使用 MediaWiki API 获取页面、修订、Wikitext 和服务端渲染 HTML，不依赖浏览器模拟点击页面。

## 2. 总体数据流

```text
MediaWiki API
    │
    ├─ 分类递归发现、修订信息读取
    ▼
增量同步计划
    │
    ├─ dry-run：只输出计划
    └─ execute：写 SQLite 和原始快照
    ▼
data/raw/wiki/{page_id}/{revision_id}.json
    │
    ├─ BeautifulSoup 解析信息框和正文
    ▼
ParsedWikiPage / WikiSection
    │
    ├─ 按语义章节切块，不跨章节拼接
    ▼
LangChain Document
    │
    ├─ BGE Embedding
    ▼
Chroma：正文 + metadata + 向量

SQLite：数据源、页面、修订、文档状态和同步审计
```

同步和索引被刻意拆成两个阶段。这样即使模型不可用或 Embedding 失败，已经下载的原始快照仍然存在，可以稍后重试索引。

## 3. 代码文件与职责

| 文件 | 当前职责 |
| --- | --- |
| `app/commands/sync_wiki.py` | 同步命令入口，解析 CLI 参数并启动异步同步服务 |
| `app/rag/mediawiki.py` | MediaWiki API 客户端、分类递归发现、页面和修订读取 |
| `app/services/wiki_sync_service.py` | 增量对比、同步计划、页面状态和同步审计编排 |
| `app/rag/wiki_snapshot.py` | 生成并保存不可变 JSON 快照，校验同路径内容一致性 |
| `app/models/wiki.py` | `wiki_sources`、`wiki_pages`、`wiki_sync_runs` 模型 |
| `app/commands/index_wiki.py` | 索引命令入口，支持 dry-run、标题过滤和数量限制 |
| `app/services/wiki_index_service.py` | 编排快照校验、解析、切块、向量替换和状态更新 |
| `app/rag/wiki_parser.py` | 将 HTML 解析为页面无关的语义章节 |
| `app/rag/splitter.py` | 在章节边界内按长度切块并补充 metadata |
| `app/rag/embeddings.py` | 延迟加载并缓存 Embedding 模型 |
| `app/rag/vectorstore.py` | Chroma 新增、查询、按文档/修订删除和版本替换 |
| `app/commands/sample_chunks.py` | 随机抽取 Chroma 切块用于人工质量检查 |

## 4. 配置

Wiki 配置集中在 `app/core/config.py`，可通过环境变量覆盖：

| 环境变量 | 默认值或作用 |
| --- | --- |
| `MEDIAWIKI_API_URL` | 缺氧中文 Wiki API 地址 |
| `MEDIAWIKI_BASE_URL` | 缺氧中文 Wiki 基础地址 |
| `MEDIAWIKI_LANGUAGE` | `zh` |
| `MEDIAWIKI_ROOT_CATEGORIES` | `建筑,小动物` |
| `MEDIAWIKI_EXCLUDED_CATEGORY_KEYWORDS` | 排除调试、未实装等分类关键词 |
| `MEDIAWIKI_SNAPSHOT_PATH` | `./data/raw/wiki` |
| `MEDIAWIKI_REQUEST_TIMEOUT` | API 请求超时，默认 30 秒 |
| `MEDIAWIKI_USER_AGENT` | 标识本项目及非商业学习用途 |
| `CHUNK_SIZE` | Wiki 长章节切块长度，默认 500 |
| `CHUNK_OVERLAP` | 相邻切块重叠长度，默认 50 |
| `CHROMA_DB_PATH` | Chroma 持久化目录，默认 `./chroma_db` |

## 5. 阶段一：页面发现和增量同步

### 5.1 页面发现

`MediaWikiClient.discover_pages()` 从配置的根分类开始，调用 MediaWiki API 获取分类成员：

1. 递归进入符合范围的子分类。
2. 只保留正文命名空间页面。
3. 跳过分类名称中包含排除关键词的分支。
4. 对发现结果按页面 ID 去重。

同步指定 `--title` 时，只处理这些页面，不会将未指定页面误判为下线。只有完整同步才执行远端下线检测。

### 5.2 增量判断

`WikiSyncService` 将远端页面引用与 SQLite 中的 `wiki_pages` 对比，生成以下动作：

- `created`：本地没有该页面。
- `updated`：远端 `revision_id` 与本地不同，或本地页面此前被标记为下线。
- `unchanged`：本地已经保存同一修订。
- `removed`：完整同步时，本地页面不再出现在远端发现结果中。

`--dry-run` 只输出计划，不创建同步运行记录，不修改 SQLite，也不下载快照。

### 5.3 同步命令

```bash
# 查看完整同步计划
python -m app.commands.sync_wiki --dry-run --verbose

# 执行完整同步
python -m app.commands.sync_wiki

# 只同步指定页面
python -m app.commands.sync_wiki \
  --title "电解器" \
  --title "人力发电机" \
  --title "好吃哈奇"
```

### 5.4 SQLite 状态

同步新页面或新修订后：

- `wiki_pages.revision_id` 保存当前已同步修订。
- `wiki_pages.indexed_revision_id` 保留当前已进入 Chroma 的修订；新页面初始为空。
- 对应 `documents.status` 设置为 `pending_index`。
- 下线页面设置为 `source_removed`，但不会在同步阶段直接破坏向量数据。
- 每次执行结果写入 `wiki_sync_runs`，用于记录范围、统计、失败信息和耗时边界。

数据库字段的完整定义见 [数据库结构说明](./database-schema.md)。

## 6. 原始快照

### 6.1 路径和不可变性

快照路径为：

```text
data/raw/wiki/{page_id}/{revision_id}.json
```

例如：

```text
data/raw/wiki/2238/37047.json
```

`WikiSnapshotStore` 使用排他创建模式写文件。同一 `page_id + revision_id` 已存在时不会覆盖；它会读取已有文件并验证内容哈希，防止相同修订路径被静默写入不同内容。

### 6.2 快照内容

快照主要包含：

```text
schema_version
source
page
content_sha256
wikitext
html
```

- `wikitext` 用于保留 Wiki 原始语义和模板调用。
- `html` 是 MediaWiki 服务端展开模板后的页面结构，是当前解析器的主要输入。
- `content_sha256` 用于检测内容不一致和索引前校验。

原始快照不是切块结果，不能直接写入向量库。它还包含导航、模板、图片和页面辅助区域，需要先进行语义解析和清洗。

## 7. 阶段二：HTML 解析

### 7.1 解析入口

`parse_wiki_snapshot()` 读取 JSON 后执行：

1. 校验根对象、`page`、`source` 和 HTML。
2. 读取页面 ID、修订 ID、标题、来源地址、分类和内容哈希。
3. 使用 BeautifulSoup 解析 HTML。
4. 优先选择 `.mw-parser-output` 作为正文根节点。
5. 先提取信息框，再提取普通正文。
6. 返回 `ParsedWikiPage`，其中包含多个 `WikiSection`。

### 7.2 Portable Infobox

新版 Wiki 信息框通过以下选择器识别：

```text
aside.portable-infobox
```

解析规则包括：

- `.pi-caption` 转换为 `说明：...`。
- `.pi-data-label` 与 `.pi-data-value` 转换为 `字段：值`。
- `.pi-section-tab[data-ref]` 和 `.pi-section-content[data-ref]` 对应不同变种。
- `section.pi-group` 和直接子级 `.pi-header` 对应信息框内部语义分组。

“好吃哈奇”页面因此可以形成以下层级：

```text
信息框 / 好吃哈奇
信息框 / 好吃哈奇 / 生存
信息框 / 好吃哈奇 / 繁殖
信息框 / 好吃哈奇 / 食谱
信息框 / 好吃哈奇 / 代谢
信息框 / 好吃哈奇 / 构成
```

分组标题被建模为独立 `WikiSection`，而不是只拼在一段长文本开头。这一点很重要：长食谱拆成多个切块时，每个切块都会重新带上完整章节路径。

解析器不会硬编码“食谱”字段，也不会只为某个页面添加规则；它依赖 portable infobox 的通用结构，因此同类页面可以复用。

### 7.3 经典信息框

旧页面可能使用：

```text
table.infobox
```

解析器逐行读取 `th` 和 `td`，将第一列作为字段名，其余列使用 `|` 连接。

### 7.4 正文章节

普通正文按 `h2` 至 `h6` 建立标题栈。当前提取的内容块包括：

- `p`：段落。
- `ul`、`ol`：列表。
- `table`：表格。
- `dl`：定义列表。
- `blockquote`：引用块。
- `pre`：预格式化内容。

正文标题路径会保留层级。例如：

```text
养殖方式 / 煤炭产出
```

解析器不会跨标题合并内容；标题出现时先结束上一个 `WikiSection`，再开始新的章节。

### 7.5 噪声清理

正文解析前会删除或排除：

- `script`、`style`、`noscript`、`template`。
- 编辑按钮和目录。
- 消息提示框 `.mbox`。
- 导航框和分类链接区域。
- 打印页脚和参考文献区域。
- 正文中的脚注标记。
- 未被信息框解析器消费的辅助 `aside`。

导航型 portable infobox 使用 `pi-theme-navbox` 排除，避免将大量无关页面名称写入当前页面切块。

## 8. 阶段三：语义切块

`split_wiki_page()` 对每个 `WikiSection` 单独切分，因此不会把两个不同章节拼进同一个切块。

默认策略：

```text
chunk_size = 500
chunk_overlap = 50
separators = 段落、换行、句号、分号、逗号、字符
```

每个生成的切块都会添加可独立理解的前缀：

```text
页面：好吃哈奇
章节：信息框 / 好吃哈奇 / 食谱

沙子 140 千克 ➤ 煤炭 70 千克……
```

关键 metadata 包括：

| 字段 | 作用 |
| --- | --- |
| `document_id` | 与 SQLite `documents.id` 关联 |
| `source_type` | 当前 Wiki 数据为 `mediawiki` |
| `source`、`title` | 页面标题 |
| `page_id` | MediaWiki 页面 ID |
| `revision_id` | MediaWiki 修订 ID |
| `revision_timestamp` | 修订时间 |
| `section` | 当前章节的末级标题 |
| `section_path` | 页面和完整章节路径 |
| `section_type` | `infobox` 或普通 `section` |
| `section_index` | 页面内语义章节序号 |
| `section_chunk_index` | 当前章节内切块序号 |
| `chunk_index`、`chunk_total` | 页面全局切块序号和总数 |
| `categories` | 页面分类，使用 `|` 连接 |
| `canonical_url` | Wiki 原页面地址 |
| `content_sha256` | 当前快照内容哈希 |
| `snapshot_path` | 对应原始快照路径 |

## 9. 阶段四：Embedding 与 Chroma 索引

### 9.1 Embedding

`get_embeddings()` 在进程内缓存一个 Hugging Face Embedding 实例：

- 模型名称由 `EMBEDDING_MODEL` 配置。
- 当前使用 CPU。
- 模型文件缓存在项目 `models/` 目录。
- 输出向量执行归一化，便于相似度比较。

删除和 metadata 查询直接使用 Chroma 原生客户端，不加载 Embedding 模型。只有新增切块和相似度检索需要 Embedding。

### 9.2 切块 ID

Wiki 切块使用确定性 ID：

```text
wiki:{page_id}:{revision_id}:{chunk_index}
```

例如：

```text
wiki:2238:37047:4
```

确定性 ID 便于重试、计数和按修订清理，也能从 ID 直接定位页面和修订。

### 9.3 新修订替换

索引服务只选择：

```text
wiki_pages.indexed_revision_id != wiki_pages.revision_id
```

的页面。正常的新修订替换顺序为：

1. 清理目标修订上次失败可能遗留的不完整切块。
2. 写入目标修订全部新切块。
3. 按 metadata 统计目标修订切块数并校验。
4. 新修订成功后删除 `indexed_revision_id` 对应的旧修订切块。
5. 更新 `indexed_revision_id`、文档状态和 `chunk_count`。

如果新修订写入失败，会删除目标修订的不完整切块并保留旧修订。这样检索端不会同时看到两个修订，也不会因为新版本失败而立即失去旧的可用索引。

### 9.4 索引命令

```bash
# 查看待索引计划
python -m app.commands.index_wiki --dry-run --verbose

# 索引全部待处理页面
python -m app.commands.index_wiki

# 索引指定页面
python -m app.commands.index_wiki \
  --title "电解器" \
  --title "人力发电机" \
  --title "好吃哈奇"

# 限制本次处理数量
python -m app.commands.index_wiki --limit 10
```

## 10. 随机抽样与质量检查

随机抽样命令用于人工检查 Chroma 中真正参与检索的内容，而不是只检查解析前 JSON：

```bash
# 默认随机抽取 5 个
python -m app.commands.sample_chunks

# 固定种子，复现同一批样本
python -m app.commands.sample_chunks --count 10 --seed 42

# 只检查指定页面
python -m app.commands.sample_chunks --title "好吃哈奇"

# 只检查指定 collection
python -m app.commands.sample_chunks --collection langchain
```

命令首先读取符合条件的 Chunk ID，然后只读取抽中的正文和 metadata；它不读取向量、不加载 Embedding 模型，也不修改 Chroma。未指定种子时，命令会生成并打印种子，发现问题后可以使用该种子复现样本。

建议人工检查以下项目：

- 页面和章节标题是否足以解释正文。
- 表格、列表和转换关系是否仍然可读。
- 是否混入导航、参考文献、版本提示或无关页面名称。
- 单个块是否过长、过短或从语义中间断开。
- metadata 的页面、修订、章节和来源地址是否正确。

## 11. 测试

Wiki 相关测试覆盖：

- 分类发现和排除规则。
- 增量计划、部分同步和下线判断。
- dry-run 不写入数据库和快照。
- 快照不可变性和内容哈希。
- portable infobox、经典信息框和正文标题解析。
- 信息框分组标题在多个切块中重复保留。
- 章节边界、切块 metadata 和序号。
- 新旧 Wiki 修订的向量替换与失败回滚。
- 索引幂等性和随机抽样行为。

运行全部测试：

```bash
python -m pytest -q
```

## 12. 当前已知限制

### 12.1 同一修订尚不能安全强制重建

解析器或切块策略发生变化，但 Wiki `revision_id` 不变时，当前索引服务会认为页面已是最新版本并跳过。项目尚未实现 `index_wiki --force`。

直接删除旧切块再重建并不安全：如果 Embedding 或 Chroma 写入失败，旧索引已经丢失。后续需要实现带备份和恢复能力的同修订重建，或引入独立的索引构建版本。

### 12.2 HTML 网格行边界可能丢失

部分信息框使用 CSS Grid 表达食谱。当前解析器可以保留“食谱”分组和箭头，但 `get_text()` 仍可能把多行网格压平成连续文本，导致切块从某一行中间开始。后续可以识别固定网格单元，将每四个单元恢复为一条“输入 ➤ 输出”记录。

### 12.3 尚未建立全量质量报告

当前采用测试页面、单元测试和随机抽样逐步验证。470 多个页面不适合逐页编写测试；后续应增加规则化质量检查，例如空章节率、超长块、疑似导航噪声、缺失标题和异常 metadata 统计。

### 12.4 索引规则没有独立版本号

快照有 `schema_version`，但当前 SQLite 和 Chroma metadata 尚未保存 parser/splitter/index pipeline 版本。后续可以加入 `index_schema_version` 或 pipeline fingerprint，让代码升级后自动识别需要重建的页面。

## 13. 文档维护要求

以下改动发生时，应同步更新本文：

- MediaWiki 抓取范围或排除规则改变。
- 快照 JSON 结构改变。
- 新增或修改 HTML 解析规则。
- 切块大小、重叠或语义边界策略改变。
- Chroma ID、metadata 或版本替换策略改变。
- 新增强制重建、全量质量检查或索引版本能力。

对应的修改原因、验证结果和遗留问题应同时追加到 [开发日志](./development-log.md)。
