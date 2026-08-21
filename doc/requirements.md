
# Personal Memory Service
# 个人长期记忆系统需求与技术设计文档

> 文档状态：Draft v0.2
> 项目阶段：需求整理 / 架构设计
> 核心目标：构建一个面向大语言模型的个人长期记忆服务，通过 PostgreSQL + pgvector 与 Neo4j 双数据源，实现语义记忆检索与知识关系检索，并最终以 MCP Server 的形式向大模型提供长期记忆能力。
> 记忆如何提取：先初步提取分类，再到对应的分类去精炼。

---

# 1. 项目背景

当前的大语言模型虽然拥有较强的上下文理解能力，但单次会话上下文并不适合作为真正的长期个人记忆系统。

本项目希望构建一个独立于具体大模型之外的 **Personal Memory Service（个人长期记忆服务）**。

该服务负责：

1. 长期保存用户记忆；
2. 对记忆进行结构化管理；
3. 对记忆建立向量索引；
4. 通过语义相似度召回相关记忆；
5. 保存和查询记忆之间的关系；
6. 综合 PostgreSQL 与 Neo4j 两个数据源的查询结果；
7. 将最终得到的上下文提供给大语言模型；
8. 最终通过 MCP 协议向外提供长期记忆能力。

系统不将某一个具体 LLM 作为数据存储主体。

LLM 负责：

- 理解用户输入；
- 判断哪些内容值得形成长期记忆；
- 生成 Memory 的摘要；
- 提取 Memory 信息；
- 判断新旧 Memory 之间的关系；
- 理解查询意图；
- 综合检索得到的 Memory；
- 对 Memory 进行推理。

Memory Service 负责：

- Memory 存储；
- Embedding 存储；
- 向量索引；
- Memory 查询；
- Memory 状态管理；
- Memory 生命周期管理；
- 人工修改保护；
- 权限管理；
- PostgreSQL 与 Neo4j 的数据访问；
- 向 MCP Client 提供统一接口。

---

# 2. 项目目标

系统的核心目标是构建：

> 一个由 LLM 驱动的双数据源个人长期记忆系统。

其中：

- PostgreSQL + pgvector 负责 Memory 的主要数据存储以及向量语义检索；
- Neo4j 负责 Memory 之间以及未来其他知识实体之间的关系存储；
- Python Service 负责协调两个数据源；
- OpenAI SDK 负责调用大语言模型以及 Embedding 模型；
- MCP Server 负责将整个 Memory Service 暴露给外部 AI Client。

系统最终应当能够实现：

- 写入长期 Memory；
- 搜索长期 Memory；
- 更新已有 Memory；
- 判断 Memory 是否已经存在；
- 判断 Memory 是否已经失效；
- 处理新旧 Memory 冲突；
- 进行向量语义召回；
- 查询知识关系；
- 将多个数据源的结果整合后提供给 LLM。

---

# 3. 核心设计原则

## 3.1 Memory Service 与 LLM 解耦

Memory Service 不应该绑定某一个具体聊天客户端或者某一个具体大模型。

未来可以被不同客户端调用，例如：

- ChatGPT；
- 自建 Agent；
- IDE Agent；
- 其他支持 MCP 的客户端。

Memory Service 本身只负责长期记忆相关功能。

具体使用哪个大语言模型，应尽可能通过配置或者 LLM Client 层进行控制，而不是将业务逻辑与某个具体模型写死。

---

## 3.2 双数据源设计

系统使用两个数据库：

### PostgreSQL + pgvector

主要负责：

- Memory 原始数据；
- Memory 内容；
- Memory 标题；
- Memory 元数据；
- Memory 状态；
- Memory 权限；
- Memory Embedding；
- 向量检索；
- SQL 条件过滤；
- Memory 生命周期管理。

### Neo4j

主要负责：

- Memory 之间的关系；
- 知识之间的关系；
- 比较关系；
- 推导关系；
- 因果关系；
- 其他未来需要通过知识图谱表达的关系。

当前阶段暂不确定 Neo4j 的具体数据结构。

Neo4j 的 Node、Relationship、Schema 以及具体关系类型将在后续单独设计。

---

## 3.3 PostgreSQL 作为主要事实数据源

Memory 的完整内容主要保存在 PostgreSQL 中。

包括：

- Memory 是否存在；
- Memory 当前状态；
- Memory 标题；
- Memory 完整内容；
- Memory Embedding；
- Memory 是否被人工修改；
- Memory 创建和修改时间；
- Memory 权限。

这些核心信息以 PostgreSQL 中的数据为准。

Neo4j 当前主要作为关系数据源，而不是 Memory 完整文本的数据源。

---

## 3.4 高内聚、细粒度 Memory

Memory 应尽量遵循：

- High Cohesion；
- Single Responsibility；
- Fine-grained Memory。

也就是说：

> 一条 Memory 尽量只表达一个相对独立的事实、状态、偏好、决定或者知识。

避免将大量彼此无关的信息存储在同一条 Memory 中。

这样可以提高：

- Embedding 精度；
- 向量搜索质量；
- Memory 更新精度；
- Memory 去重精度；
- 知识关系构建质量。

---

# 4. 已确定技术栈

## 4.1 服务端语言

已确定使用：

```text
Python
```

整个 Personal Memory Service 使用 Python 开发。

---

## 4.2 LLM SDK

主要使用：

```text
OpenAI SDK
```

OpenAI SDK 主要用于：

- 调用大语言模型；
- Memory 摘要；
- Memory 信息提取；
- Memory 去重判断；
- Memory 更新判断；
- Memory 冲突判断；
- Relationship 判断；
- 查询理解；
- Embedding 生成。

具体使用哪个 OpenAI 模型暂时不固定。

模型应该尽可能通过配置进行替换。

---

## 4.3 MCP

最终服务形式确定为：

```text
MCP Server
```

Python Memory Service 最终需要向外提供 MCP 接口。

未来支持 MCP 的 LLM Client 可以通过 MCP 调用 Memory Service。

---

## 4.4 主数据库

已确定：

```text
PostgreSQL
```

PostgreSQL 保存 Memory 的核心数据。

---

## 4.5 向量数据库

暂时不单独引入专门的 Vector Database。

使用：

```text
PostgreSQL + pgvector
```

完成：

- Embedding 保存；
- Vector Index；
- Vector Search。

这样可以避免为了向量检索再额外维护一个独立数据库。

---

## 4.6 知识图谱数据库

已确定使用：

```text
Neo4j
```

Neo4j 专门负责知识图谱和关系数据。

当前阶段仅确定技术选型和基本职责。

具体 Neo4j Schema 暂不设计。

---

## 4.7 Python Agent / LLM Framework

暂时不固定具体框架。

可以考虑：

- LangChain；
- LangGraph；
- 其他 Python Agent Framework；
- 或者直接使用 OpenAI SDK 自己实现。

当前原则是：

> Python + OpenAI SDK 是核心技术栈，Agent Framework 只是可替换的辅助工具。

不应过早让核心业务逻辑绑定某一个 Agent Framework。

---

# 5. PostgreSQL 表设计

当前 PostgreSQL 至少需要两个核心表：

1. `memory`
2. `relationship_type`

其中：

- `memory` 保存长期记忆；
- `relationship_type` 保存系统允许使用的知识关系类型。

Neo4j 相关表结构和数据结构当前暂不设计。

---

# 6. Memory 表

Memory 是整个系统最核心的数据单元。

建议初始建表语句如下：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE memory (
    id BIGSERIAL PRIMARY KEY,

    title TEXT NOT NULL,
    content TEXT NOT NULL,

    embedding VECTOR,

    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',

    manual_modified BOOLEAN NOT NULL DEFAULT FALSE,

    permission VARCHAR(64),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by VARCHAR(128),
    updated_by VARCHAR(128)
);
```

说明：

当前 `VECTOR` 暂时没有指定维度。

具体维度需要等待最终选择 Embedding Model 后再确定。

例如，如果未来确定 Embedding Dimension 为 1536，则可以调整为：

```sql
embedding VECTOR(1536)
```

具体数值当前不应提前写死。

---

# 7. Memory 字段说明

## 7.1 id

```text
id
```

Memory 的唯一主键。

使用 PostgreSQL `BIGSERIAL` 自动生成。

该 ID 后续也可以用于 PostgreSQL 与 Neo4j 之间的关联。

例如一条 PostgreSQL Memory：

```text
memory.id = 1024
```

Neo4j 后续可以通过这个 Memory ID 引用对应的 Memory。

具体 Neo4j 实现方式暂时不确定。

---

## 7.2 title

```text
title
```

Memory 的标题、摘要或者核心语义。

这是整个 Memory 系统中非常重要的字段。

title 的目标是：

> 使用尽可能短、尽可能高信息密度的文本表达这一条 Memory 的核心含义。

例如：

```text
用户更倾向使用 SBI 而不是 Monex
```

或者：

```text
用户正在开发 Flutter + Drift 词库应用
```

title 可以非常短。

当原始 Memory 本身已经非常短时，也允许：

```text
title = content
```

---

# 8. Content

```text
content
```

Memory 的完整内容。

例如：

```text
用户计划在日本长期投资美股，目前更倾向使用 SBI 证券，
主要考虑 NISA、手续费以及使用便利性。
Monex 因换汇手续费等因素暂不考虑。
```

content 主要用于：

- 保存完整 Memory；
- 最终提供给 LLM；
- 人工查看；
- 人工修改；
- 后续重新摘要；
- 后续关系提取；
- 新旧 Memory 比较。

---

# 9. Embedding 设计

一个已经确定的重要设计原则是：

> Embedding 主要针对 title，而不是 content。

也就是说：

```text
embedding = embedding(title)
```

而不是默认：

```text
embedding = embedding(content)
```

这样设计主要有以下原因：

1. title 是 Memory 的核心语义摘要；
2. title 信息密度通常比完整 content 更高；
3. 可以降低长文本中无关信息对 Embedding 的干扰；
4. 可以减少 Embedding Token 消耗；
5. 可以提高细粒度 Memory 的向量召回质量；
6. 可以让向量空间中的一条记录尽量表达一个明确概念。

因此，当前主要向量召回字段为：

```text
memory.title
```

`content` 默认不直接作为主要向量召回文本。

---

# 10. Memory 粒度

Memory 应遵循高内聚和细粒度原则。

不应该将大量互不相关的信息放进同一条 Memory。

例如下面这种 Memory 不合适：

```text
用户喜欢 SBI，
用户住在大阪，
用户学习日语，
用户主要使用 Java，
用户最近在研究 Neo4j。
```

这些内容应该拆成多条独立 Memory。

例如：

```text
用户更倾向使用 SBI 证券。
```

```text
用户目前居住在大阪。
```

```text
用户主要拥有 Java 后端开发经验。
```

```text
用户正在研究 PostgreSQL + Neo4j 的长期记忆系统。
```

这种设计有利于后续：

- 搜索；
- 去重；
- 更新；
- 失效；
- 图谱关系建立。

---

# 11. Memory 人工修改保护

系统必须能够区分：

- AI 自动产生或者维护的 Memory；
- 用户人工修改过的 Memory。

因此设计字段：

```text
manual_modified
```

默认值：

```text
false
```

表示该 Memory 尚未被用户人工修改。

如果用户人工修改：

```text
manual_modified = true
```

则系统遵循一个重要原则：

> 人工修改过的 Memory 默认禁止 AI 自动覆盖。

AI 在进行自动 Memory Update 之前必须检查：

```text
manual_modified
```

如果：

```text
manual_modified = true
```

则默认不得直接覆盖原记录。

如果发现新事实与人工维护的 Memory 冲突，可以：

- 创建新的 Memory；
- 标记冲突；
- 建立关系；
- 提醒用户；

但不能静默修改用户人工维护的内容。

---

# 12. Memory 状态

Memory 不应该只使用物理删除管理生命周期。

需要通过：

```text
status
```

字段管理 Memory 生命周期。

当前可以先预留类似状态：

```text
ACTIVE
EXPIRED
DISABLED
DELETED
```

具体枚举后续可以再调整。

其中：

### ACTIVE

当前有效 Memory。

### EXPIRED

Memory 曾经有效，但已经因为时间或者新信息而失效。

例如旧 Memory：

```text
用户目前住在东京。
```

后来产生新 Memory：

```text
用户目前住在大阪。
```

那么旧 Memory 更适合标记：

```text
EXPIRED
```

而不是直接删除。

这样可以保存历史。

### DISABLED

Memory 被用户或者系统暂时禁止参与正常召回。

### DELETED

逻辑删除状态。

是否最终需要保留 `DELETED` 状态，或者直接物理删除，可以后续决定。

---

# 13. Memory Audit

Memory 表需要保存基础审计信息：

```text
created_at
updated_at
created_by
updated_by
```

这些字段可以用于：

- 判断 Memory 创建时间；
- 判断 Memory 更新时间；
- 区分用户修改与系统修改；
- 排查 AI 自动修改问题；
- 实现 Memory 历史管理；
- 后续进行数据审计。

例如：

```text
created_by = "llm"
updated_by = "user"
```

或者：

```text
created_by = "user"
updated_by = "system"
```

具体枚举值后续统一设计。

---

# 14. Permission

Memory 表预留：

```text
permission
```

字段。

主要是为未来权限体系留下扩展空间。

未来可能存在：

```text
PRIVATE
SHARED
SYSTEM
```

或者进一步扩展为更复杂的权限模型。

第一阶段暂时不需要实现复杂权限控制。

---

# 15. Relationship Type 表

虽然具体 Neo4j Schema 当前暂不设计，但之前已经确定一个重要方向：

> 知识关系类型不应该全部硬编码在 Python 业务代码中。

因此可以在 PostgreSQL 中维护一个关系类型定义表。

建表语句：

```sql
CREATE TABLE relationship_type (
    id BIGSERIAL PRIMARY KEY,

    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128),
    description TEXT,

    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

其中：

```text
code
```

表示关系类型的程序标识。

例如未来可能存在：

```text
RELATED_TO
COMPARE_WITH
DERIVED_FROM
CAUSES
PREFERS_OVER
```

这里仅作为示例。

具体有哪些 Relationship Type 目前暂不确定。

Python Service 启动时，可以从 PostgreSQL 加载当前允许使用的 Relationship Type。

在调用 LLM 判断知识关系时，可以将：

```text
当前允许使用的 Relationship Type
```

提供给模型。

这样可以避免 LLM 自由创造大量不可管理的关系类型。

---

# 16. PostgreSQL 查询策略

Memory 查询不能只有单纯的 Vector Search。

应该支持：

```text
SQL 条件过滤 + Vector Search
```

例如：

```sql
SELECT
    id,
    title,
    content,
    status,
    manual_modified,
    permission,
    created_at,
    updated_at,
    created_by,
    updated_by
FROM memory
WHERE status = 'ACTIVE'
ORDER BY embedding <=> :query_embedding
LIMIT 20;
```

这样可以先通过 SQL 条件过滤：

- status；
- permission；
- user；
- 时间；
- 未来其他 metadata；

然后再进行向量相似度排序。

---

# 17. pgvector 距离算法

pgvector 支持多种向量距离计算方式。

例如：

- Cosine Distance；
- L2 Distance；
- Inner Product。

当前暂时不完全固定最终算法。

默认可以优先研究：

```text
Cosine Similarity / Cosine Distance
```

最终需要根据：

- 实际使用的 Embedding Model；
- Memory 数据特征；
- 实际召回效果；

决定。

---

# 18. Vector Index

pgvector 后续需要根据数据量建立向量索引。

主要可以考虑：

```text
HNSW
```

或者：

```text
IVFFlat
```

当前阶段不需要提前定死。

系统早期 Memory 数量较少时，可以先使用简单 Vector Search。

等数据量达到一定规模以后，再针对实际数据：

- 建立索引；
- 调整参数；
- 测量查询性能；
- 测量 Recall；
- 决定最终索引类型。

---

# 19. Memory 更新逻辑

当系统从新的对话或者其他数据中提取出新的 Memory 时，不应该直接无条件插入数据库。

首先需要查询现有 Memory，判断是否已经存在语义相近或者相关的记录。

系统可以首先根据新 Memory 的 title 生成 Embedding，然后在 PostgreSQL 中搜索若干条语义最接近的现有 Memory。

之后将新 Memory 和这些候选 Memory 提供给 LLM，由 LLM 判断它们之间属于哪一种情况。

至少需要考虑以下几类情况：

### 1. 完全新的 Memory

数据库中不存在相同或者基本相同的信息。

这种情况下创建新的 Memory。

### 2. 重复 Memory

数据库中已经存在表达相同事实的 Memory。

这种情况下原则上不再创建新的记录。

必要时可以更新已有 Memory 的时间或者其他元数据。

### 3. 已有 Memory 的补充

新的信息并没有推翻旧信息，而是在原有 Memory 基础上增加了新的细节。

这种情况下可以考虑更新已有 Memory，也可以根据 Memory 粒度原则拆分成新的 Memory。

具体采用哪一种方式需要由 LLM 根据语义和 Memory 粒度进行判断。

### 4. 已有 Memory 的更新

新的信息意味着旧 Memory 已经发生变化。

例如旧 Memory：

```text
用户目前使用 A。
```

后来变成：

```text
用户目前已经改用 B。
```

这种情况下可以将旧 Memory 标记为：

```text
EXPIRED
```

然后创建新的 `ACTIVE` Memory。

是否直接修改旧 Memory，需要根据该 Memory 是否需要保留历史信息决定。

### 5. Memory 冲突

新信息与已有信息直接矛盾，但系统目前无法确定哪个是真实或者最新的。

此时不应该直接覆盖。

可以暂时同时保留两条 Memory，并等待：

- 更多上下文；
- 后续信息；
- 用户人工确认；

再决定如何处理。

### 6. 人工修改 Memory

如果候选 Memory：

```text
manual_modified = true
```

则 AI 默认不得直接修改或者覆盖。

即使发现新的信息，也应该优先：

- 新增 Memory；
- 保留原 Memory；
- 记录冲突或者关系；
- 必要时等待用户确认。

---

# 20. Memory 去重

Memory 写入前应该进行去重。

基本思路是：

1. 提取新的 Memory；
2. 生成 title；
3. 为 title 生成 Embedding；
4. 在 PostgreSQL 中进行 Vector Search；
5. 找到若干最相似的现有 Memory；
6. 将候选 Memory 与新 Memory 提供给 LLM；
7. 由 LLM 判断是新增、重复、更新还是冲突；
8. 根据判断结果执行对应数据库操作。

LLM 可以输出类似以下语义状态：

```text
NEW
DUPLICATE
UPDATE
CONFLICT
```

具体枚举后续再正式定义。

Vector Search 只负责：

> 找到可能相关的候选 Memory。

最终是否真正重复，不能单纯依靠向量距离决定。

需要由 LLM 进一步判断语义。

---

# 21. 人工 Memory 管理

未来应该允许用户直接管理自己的 Memory。

至少包括：

- 创建 Memory；
- 查看 Memory；
- 修改 Memory；
- 禁用 Memory；
- 删除 Memory；
- 恢复 Memory；
- 锁定 Memory。

用户人工修改 Memory 后：

```text
manual_modified = true
```

AI 后续默认不得自动覆盖。

人工管理功能第一阶段可以不开发完整 UI。

可以首先通过：

- MCP Tool；
- API；
- 开发管理接口；

实现。

---

# 22. MCP Tool 初步设计

最终 MCP Server 可以向 LLM 暴露 Memory 能力。

当前可以考虑以下 Tool。

## memory_search

作用：

> 根据自然语言搜索相关 Memory。

内部可以执行：

- Embedding；
- PostgreSQL Vector Search；
- SQL Filter；
- 后续 Neo4j 查询；
- Result Merge。

---

## memory_get

作用：

> 根据 Memory ID 获取完整 Memory。

---

## memory_create

作用：

> 创建新的 Memory。

实际创建前可以执行：

- Memory Normalization；
- 去重；
- Embedding；
- 状态初始化。

---

## memory_update

作用：

> 更新已有 Memory。

需要遵守：

```text
manual_modified
```

保护规则。

---

## memory_disable

作用：

> 将 Memory 设置为禁用状态。

---

## memory_graph_search

作用：

> 查询某个 Memory 或者某个概念相关的知识图谱关系。

该 Tool 的具体实现暂时等待 Neo4j Schema 确定以后再设计。

---

## memory_context

这是未来比较重要的高级 Tool。

作用：

> 根据当前问题自动查询长期 Memory，并返回适合直接提供给 LLM 的 Context。

未来内部可以综合：

- Vector Search；
- Graph Search；
- SQL Filter；
- Ranking；
- Context Selection；
- Token Budget。

第一阶段可以先只实现 PostgreSQL Vector Search。

---

# 23. Python 项目模块划分

Python 项目暂时不需要过早确定具体目录结构，但从职责上可以分为以下几大模块。

## MCP 模块

负责：

- 启动 MCP Server；
- 注册 MCP Tools；
- 接收 MCP Client 请求；
- 将请求转发给内部 Service。

MCP 层尽量只负责协议适配，不承载大量业务逻辑。

---

## Memory 模块

负责 Memory 核心业务。

包括：

- Memory 创建；
- Memory 查询；
- Memory 更新；
- Memory 状态管理；
- Memory 去重；
- Memory 冲突处理；
- Memory 人工修改保护。

这是整个项目最核心的业务模块。

---

## Retrieval 模块

负责 Memory 检索。

包括：

- Query Embedding；
- Vector Search；
- SQL Filter；
- Result Ranking；
- 后续 Graph Retrieval；
- 多数据源结果合并；
- Context 构建。

---

## LLM 模块

负责所有与大语言模型交互的逻辑。

第一阶段主要使用：

```text
OpenAI SDK
```

负责：

- Memory 提取；
- Memory 摘要；
- title 生成；
- Memory 去重判断；
- Memory 更新判断；
- Memory 冲突判断；
- Relationship 判断；
- Query Understanding。

应该尽量通过统一的 LLM Client 封装 OpenAI SDK，避免业务代码直接散落大量 SDK 调用。

---

## Embedding 模块

负责：

- 调用 Embedding Model；
- 根据 title 生成 Embedding；
- 管理 Embedding Model 配置；
- 后续处理模型切换问题。

Embedding 逻辑应该和 Memory 业务逻辑分离。

---

## PostgreSQL 数据访问模块

负责：

- PostgreSQL Connection；
- Memory CRUD；
- pgvector 查询；
- Relationship Type 查询；
- Transaction；
- SQL 封装。

业务层不应该直接散落大量 SQL。

---

## Neo4j 数据访问模块

负责未来的：

- Neo4j Connection；
- Graph Query；
- Relationship 写入；
- Relationship 查询。

具体实现等待 Neo4j Schema 确定后再继续设计。

---

## Configuration 模块

负责统一管理：

- OpenAI API 配置；
- Model 配置；
- Embedding Model 配置；
- PostgreSQL 配置；
- Neo4j 配置；
- MCP 配置；
- Logging 配置；
- 其他运行参数。

敏感配置不应直接写死在代码中。

---

# 24. 当前阶段总结

目前已经确定的核心技术路线如下：

| 项目 | 当前决定 |
|---|---|
| Backend | Python |
| LLM SDK | OpenAI SDK |
| 对外协议 | MCP Server |
| 主数据库 | PostgreSQL |
| Vector | pgvector |
| Graph Database | Neo4j |
| Memory 完整数据 | PostgreSQL |
| Embedding 存储 | PostgreSQL |
| Embedding 来源 | Memory Title |
| 知识关系 | Neo4j |
| Memory 粒度 | Fine-grained |
| Memory 原则 | High Cohesion / Single Responsibility |
| 人工修改保护 | AI 默认不得覆盖 |
| Memory Lifecycle | Status 管理 |
| 向量查询 | SQL Filter + Vector Search |
| Relationship Type | PostgreSQL 集中维护 |
| Agent Framework | 暂不固定 |
| Neo4j Schema | 暂不设计 |

当前最适合继续推进的部分是：

1. 完善 PostgreSQL `memory` 表；
2. 确定 Memory Status 枚举；
3. 确定 Memory 写入和更新规则；
4. 确定 Embedding Model；
5. 确定 pgvector 的向量维度；
6. 设计最初版本的 MCP Tools；
7. 完成只基于 PostgreSQL + pgvector 的第一版 Memory Service；
8. 等第一版 Memory 系统跑通以后，再单独研究 Neo4j 的知识图谱 Schema。

Neo4j 当前只确定：

> 使用 Neo4j 作为关系数据源。

其具体 Node、Relationship、Graph Schema、Relation 建模方案暂时全部留到下一阶段单独设计。