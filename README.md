# Thoth

基于 Python、FastMCP 和 PostgreSQL 的日语单词 MCP 服务。提供单词写入、使用与陌生计数、清零、查询及已有用户查询。参数直接使用 JSON 数组和对象，FastMCP 根据类型定义生成带中文字段说明的输入、输出 Schema。

服务不调用大模型、不生成向量，也不向 AI 提供任意 SQL 或表结构修改接口。项目原有依赖暂时保留。

## 配置与启动

使用 Python 3.11 或更高版本，以及项目现有的虚拟环境。配置目录固定为项目根目录，不依赖启动时的工作目录。

首次配置时复制 `.env.example` 为 `.env`，复制需要使用的 `.env.dev.example`、`.env.test.example` 或 `.env.prd.example` 为对应环境文件，并填写真实数据库凭证。正式生产配置仅放在正式部署目录；真实 `.env` 和 `.env.*` 文件均不提交 Git。

| 文件 | 用途 | 对应数据库 |
| --- | --- | --- |
| `.env` | 通过 `THOTH_ENV=dev` 选择默认环境，并存放公共配置；禁止放连接串 | — |
| `.env.dev` | 开发版 Thoth 配置 | `thoth_dev` |
| `.env.test` | 集成测试配置 | `thoth_test` |
| `.env.prd` | 正式部署配置 | `thoth_memory` |

| 配置项 | 说明 |
| --- | --- |
| `THOTH_ENV` | 必填，仅允许 `dev`、`test`、`prd`；进程变量优先于公共 `.env`。 |
| `THOTH_PG_DSN` | 必填，存放在选中的环境文件或进程变量中。三个环境使用相同配置名。 |
| `THOTH_OPERATOR` | 可选，写入审计字段的操作者标识，默认 `THOTH_MCP`。 |

配置值优先级为进程变量 > 选定环境文件 > 公共 `.env`。每次只加载一个环境文件，不修改全局进程变量，也不展开 `${VAR}`。环境名非法、环境文件缺失或连接串为空时直接报错，不回退其他环境。即使使用进程连接串，对应环境文件也必须存在。配置首次使用后缓存，修改配置需重启服务。

数据库连接建立后，先只读查询实际库名，再核对环境与库名映射；不匹配时关闭连接，拒绝执行业务 SQL。该检查用于防止误连，不代替数据库账户权限隔离。

```shell
# 采用 .env 中的默认环境
.venv/bin/python -m thoth.mcp_server
# 在正式部署目录显式选择生产环境
THOTH_ENV=prd .venv/bin/python -m thoth.mcp_server
```

MCP 客户端也可在服务启动配置的 `env` 中设置 `THOTH_ENV`。Docker 自带 PostgreSQL MCP 使用它自己的连接设置，不读取本项目环境文件，开发时继续指向 `thoth_dev`。

迁移旧配置时，将公共 `.env` 中的 `THOTH_PG_DSN` 移入 `.env.dev`，将 `THOTH_TEST_PG_DSN` 移入 `.env.test` 并改名为 `THOTH_PG_DSN`；旧测试变量不再读取。

运行不需要 OpenAI API Key。服务使用已有的单词表、标签表及关联表，不自动建表、修改表结构或调整数据库账号权限。

在项目根目录启动 stdio MCP 服务：

```shell
.venv/bin/python -m thoth.mcp_server
```

MCP 客户端应使用虚拟环境中 Python 的绝对路径，启动参数为 `-m thoth.mcp_server`。相关命令见 [doc/commands.md](doc/commands.md)。

## 用户与统计归属

五个有参工具均要求独立的 `username`，与 `words` 或 `query` 并列，不增加最外层 request 包装。
用户名按原文区分大小写，允许中文，长度为 1～128 字符，不能含首尾空白。
用户名须手动通过 SQL 添加；非法或不存在时返回工具错误，不自动创建或选择默认用户。
结构和类型错误在进入业务层前整批拒绝；空统计数组或全部文本被过滤时仍校验用户。

| 工具 | 业务参数 | 返回值 |
| --- | --- | --- |
| `add_update_words` | 非空 `words` 对象数组 | 单词保存结果 |
| `count_word_usage` | `words` 字符串数组 | 使用计数结果 |
| `count_word_miss` | `words` 字符串数组 | 陌生计数结果 |
| `reset_word_miss` | `words` 字符串数组 | 清零结果 |
| `query_words` | `query` 查询对象，全部查询传 `{}` | 选定字段的单词结果 |
| `query_users` | 无参数 | 已有用户名 |

所有响应均为 `{"results": [...]}`，由明确的 Response 模型序列化。
旧的 `text` 字符串参数不再接受；更新调用方并刷新工具定义。单词操作改用顶层 `action`，
查询相等条件改用 `eq` 对象，排序改用字段与方向对象。本次接口更新无需数据库迁移。

`query_users()` 无参数，按用户 ID 升序返回 `{"results":[{"username":"ethan"}]}`；无用户返回空数组。
这个工具只读，不返回用户 ID 或审计信息。MCP 不提供用户新增、修改、删除或单词删除、恢复工具。
本地用户名仅用于数据分组，不是登录认证；调用方能够指定任何已有用户名。

单词、释义、读音和标签全员共享；保存工具校验用户后修改共享词库。
两张统计表以 `(user_id, word_id)` 为联合主键；计数、清零、统计筛选和排序只针对指定用户。
当前用户没有统计记录时按零处理，仍能查询共享词库，查询不会初始化统计。
`THOTH_OPERATOR` 继续用于审计字段，不代替统计归属用户。

统计调用示例（用户名需要预先添加）：

```json
{"username":"ethan","words":["食べる"]}
```

查询指定用户的高陌生次数单词：

```json
{"username":"ethan","query":{"sort":[{"field":"miss_count","direction":"desc"}],"limit":10}}
```

## 数据库完整重建与手动添加用户

**[sql/rebuild_all.sql](sql/rebuild_all.sql) 会清空全部七张项目表的数据，重复执行也会再次清空。**
脚本在一个事务中按依赖顺序删除并重建用户、单词、状态、标签、标签关联和两张统计表，再初始化状态和标签字典。
不迁移旧数据，不删除数据库或 schema，不使用 DROP CASCADE；外部依赖导致失败时整体回滚。
用户表初始为空，单词和统计也为空。

执行顺序：停止 MCP → 在 SQL 客户端确认目标数据库 → 完整执行重建脚本 → 手动添加用户 → 启动新版 MCP。
生产环境由使用者自行执行；脚本不包含连接信息。请整份执行，不选择部分语句运行，客户端报错应停止并回滚。
建表顺序为 `user_tbl`、`word_sts_tbl`、`tag_tbl`、`word_tbl`、`word_tag_tbl`、`word_usage_tbl`、`word_miss_tbl`。

手动添加用户可参考 [sql/manual/add_user.sql](sql/manual/add_user.sql)，替换示例用户名后单独执行：

```sql
INSERT INTO user_tbl (username) VALUES ('ethan')
ON CONFLICT (username) DO NOTHING;
```

合并脚本由分表 DDL 和字典 DML 生成；修改源 SQL 后同步生成，命令不会连接数据库：

```shell
.venv/bin/python -m thoth.utils.generate_rebuild_sql
.venv/bin/python -m thoth.utils.generate_rebuild_sql --check
```

## add_update_words

`username` 与非空 `words` 对象数组直接传入，每个单词可独立指定 `action`。
`action` 省略时为 `create`，明确指定 `update` 才允许修改已有单词；未知字段拒绝整批。

- **新增**：`word`、`common_form`、`hiragana`、`meaning` 都必须为非空字符串；缺失、`null`、空字符串或纯空白字符串均报错。`update` 未找到已有单词时，也适用此要求。
- **修改**：只有明确指定 `update` 才允许修改已有数据。仅覆盖传入有效非空字符串的信息字段；`common_form`、`hiragana`、`meaning` 未传入或值为 `null`、空字符串、纯空白字符串时忽略，保留原值。每次更新必须提供完整的 `tags`，仅修改标签也执行更新。
- **标签**：新增和更新均必须提供非空 `tags` 数组，不接受缺失、`null`、空数组或非法编码。编码为 1～32 位英文字母、数字或下划线，区分大小写且不去空格，重复项去重。所有标签必须已存在于 `tag_tbl`。AI 找不到合适的已有标签时不要提交该单词，不得随意选择或编造标签。
- **标签替换与事务**：更新时删除该单词全部旧标签关联，再插入完整新列表，即使新旧相同也重建，不支持清空。单词与标签共同提交或回滚，每项独立事务。`create` 遇到已有词时仍校验标签，合法后整项跳过。
- **操作控制**：`action` 只接受 `create` 或 `update`，不能为 null；不存入单词表。
- **匹配与字段范围**：按 `word` 精确匹配，包括已标记删除的记录；不修改 `word` 或记录状态。仅接受上述字段和嵌套结构，同一批次不允许重复的 `word`。
- **结果**：结构合法后每项独立处理，单项业务失败不影响其他项。按输入顺序返回数组索引 `index`（从 0 开始）、`word` 和处理状态：`created`、`updated`、`skipped` 或 `failed`。跳过或失败时附上原因，新增信息不完整时明确指出需要补齐的字段。

新增单词：

```json
{
  "username": "ethan",
  "words": [
    {"word":"食べる","common_form":"食べる","hiragana":"たべる","meaning":"吃","tags":["v","v2"]}
  ]
}
```

修改释义并提供完整标签列表：

```json
{
  "username": "ethan",
  "words": [
    {"word":"食べる","meaning":"吃；食用","tags":["v","v2"],"action":"update"}
  ]
}
```

`word` 和合法的非空 `tags` 必填；错误类型、未知字段、非法 action 或标签编码拒绝整批，
不会写入任何单词。空白单词、不可写入数据库的文本、标签不存在、实际新增信息不足等业务问题逐项返回 failed。

## 单词统计

`count_word_usage` 为使用次数加一，`count_word_miss` 为陌生次数加一。
两者直接接受单词字符串数组：

```json
{"username":"ethan","words":["食べる","飲む"]}
```

空数组正常返回空 `results`。数组中的 null、数字、对象等非字符串值拒绝整批。
字符串中的空值、纯空白及非法数据库文本逐项跳过；同批重复词仅首次出现项计数，后续项说明首次下标。
有效词按原文精确匹配，不去首尾空格；不存在或已删除的单词跳过。

每批先查询用户，再通常执行三条统计 SQL：查询单词主表、批量插入缺失的零值统计行、批量将计数加一。
只操作工具对应的统计表；写入时再次限定主表存在且未删除。
使用 autocommit，不设置跨语句或逐词事务。初始化成功而加一失败时，零值行保留。
批量写入失败则待计数项全部 failed，已过滤项仍 skipped；不自动降级逐项重试。
主表并发变化可能导致跳过或整条语句失败，不承诺跨语句快照。

返回 `results`，按原输入顺序包含零基 `index`、`word`、`status`。
updated 项的 `counts` 只包含本工具对应字段及更新后计数，skipped 和 failed 附 `reason`。
无法安全输出的 word 为 null；只有最终 RETURNING 中的记录报告成功，处理期间未更新到
的记录返回 skipped。每次成功调用均独立加一，没有请求幂等或自动重试保证。
配置、连接、初始查询失败，以及参数结构或类型错误返回工具错误。

`reset_word_miss` 使用相同的字符串数组输入：

```json
{"username":"ethan","words":["食べる"]}
```

清零仅操作已有错误计数，每词独立事务；没有记录或已经为零时跳过，不创建记录，
不修改零值行审计信息，不影响使用次数。预处理与两个计数工具一致：无效业务文本跳过，
重复词仅首次处理，后续项注明首次下标；空数组或全部过滤时仍连接数据库校验用户，但不执行单词查询和统计写入。
成功或已有零值时返回 `counts: {"miss_count": 0}`；无统计记录时省略 counts。

三个专属 Service 共用 `prepare_word_list` 过滤与去重，保留原始 index。
业务结果由入口转换为响应子模型，数据库记录由各表 entity 承载。
数据库需预先存在两张统计表，服务不会自动建表。

## query_words

`username` 与必填的 `query` 对象并列传入，`query` 可以组合以下字段：

| 参数 | 用途 | 省略时 |
| --- | --- | --- |
| `where` | 条件对象，各字段和同字段的多个操作均按 AND 组合 | 无额外条件 |
| `fields` | 返回字段数组 | 全部七个业务字段 |
| `sort` | 按优先级排列的 `[{"field":字段,"direction":"asc"或"desc"}]` | 单词 ID 升序 |
| `limit` | BIGINT 范围内的正整数 | 返回全部匹配结果，不静默截断 |

| 业务字段 | 支持的筛选 |
| --- | --- |
| `word`、`hiragana`、`meaning` | `eq`、`in` |
| `common_form` | `eq`、`in`、`like` |
| `tags` | `in`，拥有任意指定编码，不推断标签层级 |
| `usage_count`、`miss_count` | `eq`、`in`、`gt/gte/lt/lte`；值为 BIGINT 范围内非负整数 |

除 `tags` 外均可排序，排序并列追加单词 ID 升序。筛选和排序使用的字段不必返回。
字符串原文匹配，不自动修剪空白或转换写法。相等条件使用对象，例如 `{"word":{"eq":"食べる"}}`，不接受直接值简写。
不支持跨字段 OR、分页、聚合或调用方指定 SQL、表名和关联。

实际调用示例：

```json
{
  "username": "ethan",
  "query": {
    "where": {
      "common_form": {"like": "%食%"},
      "tags": {"in": ["v"]},
      "usage_count": {"lte": 5}
    },
    "fields": ["word", "common_form", "usage_count"],
    "sort": [
      {"field": "usage_count", "direction": "asc"},
      {"field": "miss_count", "direction": "desc"}
    ],
    "limit": 10
  }
}
```

查询全部单词传 `{"username":"ethan","query":{}}`。每个排序对象的 `field` 和 `direction` 均必填。
条件对象可同时包含多个支持的操作，例如 `{"miss_count":{"gte":3,"lt":10}}`。

`like` 原样使用 PostgreSQL `LIKE`：`"食%"` 匹配开头，`"%る"` 匹配结尾，`"%食%"` 匹配包含，
`_` 匹配单个字符。不自动加通配符，不改用 `ILIKE`。反斜杠转义字面通配符，
例如 JSON `{"where":{"common_form":{"like":"%\\%"}}}` 匹配以字面 `%` 结尾的常用写法。
`in` 与 `like` 可以同时出现在 `common_form` 条件中，两者必须同时满足。

固定排除 `status_code = 'D'` 的单词，不接受状态条件覆盖。按需关联指定用户的统计表记录，
无统计记录统一按 0 筛选、排序和返回，查询不会初始化或更新统计记录。
标签筛选使用 EXISTS，标签返回为按编码排序的数组，一词多标签不会重复或占用多条 limit。

返回 `{"results":[对象,...]}`，每项仅包含选定字段；单字段查询仍返回对象，无匹配为空数组。
不返回总数，不合并常用写法相同的不同单词。四个审计字段不开放查询。
拒绝未知字段/操作、显式 null、非整数或布尔计数/limit、重复投影/排序字段，
以及空的 fields、sort、in、字段条件对象。空对象和空 where 合法；空文本和空 LIKE 模式沿用数据库语义。
输入校验失败不访问数据库，连接或查询失败返回脱敏工具错误。

## 标签目录维护

`src/thoth/common/tags.py` 中的 `TAG_DEFINITIONS` 是唯一人工维护的完整标签目录，包含编码及中日文名称。
写入与查询请求模型的标签字段说明复用 `TAG_OPTIONS_DESCRIPTION`，生成 Schema 不连接数据库。
修改目录后重启 MCP 服务即可更新工具说明；示例中的少量编码不构成另一份标签清单。

标签初始化 SQL 是派生产物，不手工编辑。在项目根目录执行：

```shell
.venv/bin/python -m thoth.utils.generate_tag_sql
.venv/bin/python -m thoth.utils.generate_tag_sql --check
```

第一条命令生成 `sql/dml/dml__tag_tbl.sql`，第二条只检查文件是否与常量一致。
命令不连接或修改数据库，SQL 执行时仅插入缺失编码，保留已有标签记录。
数据库标签仍需显式初始化或迁移；修改常量不会自动修改已存名称或删除标签。
写入时仍校验标签是否存在于数据库，不改为仅按常量校验。

## 代码结构

接口与业务层之间的数据流：

```text
JSON 参数 → FastMCP 校验 → 请求模型 → 工具入口映射 → 内部 DTO / 简单参数
→ Service → 内部业务结果 → 工具入口映射 → Response → MCP 响应
```

- `mcp_server.py` 创建唯一 FastMCP 实例并启动，`tools/__init__.py` 统一注册。
- `tools/<工具全名>_tools.py` 一工具一文件，包含总说明、参数声明、映射、Service 调用和协议异常转换。
- `dto/request` 存放对外请求及子模型，`dto/response` 存放响应及子模型；字段类型、中文含义和结构约束随 Schema 暴露。
- `dto` 中其他模块承载内部业务指令、查询和结果；Service 不导入接口模型或 FastMCP。
- `service/<工具全名>_service.py` 管理专属业务流程、连接、业务校验、并发冲突和事务，不负责对外 JSON 序列化。
- `dao` 按一张表一个 `<完整表名>_mapper.py` 组织，封装 SQL 与实体映射，不决定业务分支或管理事务。
- `entity` 对应七张表，字段名称及类型与表一致，全部允许 None 且默认 None，不进行业务校验。
- `utils/sql_query_builder.py` 构建查询模板与绑定参数，Mapper 提供可信字段和关联定义。
- `db/connection.py` 管理数据库连接，`common/config.py` 管理运行配置。

保存流程先批量查询已有单词，再按输入顺序逐项保存；单词与标签共用每项事务。
更新先取得单词行锁，再替换全部标签，任何一步失败整项回滚。

数据库读取和 RETURNING 不包含业务未使用的四个审计字段；实体中这些字段保持 None，数据库审计写入行为不变。

执行测试：

```shell
.venv/bin/python -m pytest
```


# 常用命令

以下命令在项目根目录执行，使用已安装项目依赖的 `.venv`。

## 启动 MCP

先按上文准备 `.env` 和对应环境文件。默认选择 `dev`，正式部署显式指定 `THOTH_ENV=prd`；连接串必须与环境对应的数据库匹配。

```shell
.venv/bin/python -m thoth.mcp_server
```

服务通过 stdio 提供 `add_update_words`、`count_word_usage`、`count_word_miss`、`reset_word_miss` 和 `query_words`，五个有参工具接收 `username` 与原生 `words` 数组或 `query` 对象，另提供无参数的 `query_users()`。配置 MCP 客户端时，将命令设为项目 `.venv/bin/python` 的绝对路径，参数设为：

```json
["-m", "thoth.mcp_server"]
```

数据库中应已存在用户表、单词表、状态表、标签表、关联表和两张统计表；用户和标签字典需事先维护；启动服务不会执行建表、扩展安装或账号权限变更。

## 执行测试

```shell
.venv/bin/python -m pytest
```

## PostgreSQL 集成测试

单元测试不需要数据库。真实查询、并发、事务回滚和审计验证使用专用测试库：
测试入口固定调用配置加载器选择 `test`，无视公共 `.env` 和进程 `THOTH_ENV` 的日常环境选择。
在 `.env.test` 中设置 `THOTH_PG_DSN` 指向 `thoth_test`，执行：

```shell
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m pytest tests/integration
```

进程中的 `THOTH_PG_DSN` 仍具有最高优先级；如果它误指向开发库或生产库，实际库名检查会在任何测试写入前拒绝执行。
测试配置缺失或连接失败时明确失败，不跳过、不回退其他环境。
每次连接先确认实际数据库名为 `thoth_test`，确认后才允许写入。
每个测试在测试库中创建随机独立 schema，正常完成或断言失败时在 finally 中删除该 schema 及其中的表和数据；不会清空整个库。
进程被强制终止时可能残留临时 schema，不会自动删除其他测试的 schema。测试账号需要创建 schema 的权限。
