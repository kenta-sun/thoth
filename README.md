# Thoth

基于 Python、FastMCP 和 PostgreSQL 的日语单词 MCP 服务。提供 `add_update_words(text: str)`、`count_word_usage(text: str)`、`count_word_miss(text: str)`、`reset_word_miss(text: str)` 和 `query_words(text: str)`，由 AI 整理单词信息及标签，再通过固定业务接口写入已有的 `word_tbl` 和 `word_tag_tbl`。

服务不调用大模型、不生成向量，也不向 AI 提供任意 SQL 或表结构修改接口。项目原有依赖暂时保留。

## 配置与启动

使用 Python 3.11 或更高版本，以及项目现有的虚拟环境。配置可放在项目根目录的 `.env` 中，或通过环境变量传入；环境变量优先。

| 配置项 | 说明 |
| --- | --- |
| `THOTH_PG_DSN` | 必填，PostgreSQL 连接字符串，指向已有的单词数据库。 |
| `THOTH_OPERATOR` | 可选，写入审计字段的操作者标识，默认 `THOTH_MCP`。 |

运行不需要 OpenAI API Key。服务使用已有的单词表、标签表及关联表，不自动建表、修改表结构或调整数据库账号权限。

在项目根目录启动 stdio MCP 服务：

```shell
.venv/bin/python -m thoth.mcp_server
```

MCP 客户端应使用虚拟环境中 Python 的绝对路径，启动参数为 `-m thoth.mcp_server`。相关命令见 [doc/commands.md](doc/commands.md)。

## add_update_words

唯一参数 `text` 为非空 JSON 数组字符串，每个元素代表一个单词。下面展示字符串解析后的结构：

```json
[
  {
    "word": "字符串；单词基本形式，每项必填且不能为空，用于精确判重和更新定位。",
    "common_form": "字符串；常用写法，新增时必填，可以与 word 相同。",
    "hiragana": "字符串；平假名读音，新增时必填。",
    "meaning": "字符串；中文释义，新增时必填。",
    "tags": ["必填的已有标签编码，如 v、v2，至少一个"],
    "operation": {
      "action": "字符串；仅允许 create 或 update。整个 operation 可以省略，省略时默认 create。create：不存在则新增，已存在则跳过；update：不存在则新增，已存在则修改。"
    }
  }
]
```

- **新增**：`word`、`common_form`、`hiragana`、`meaning` 都必须为非空字符串；缺失、`null`、空字符串或纯空白字符串均报错。`update` 未找到已有单词时，也适用此要求。
- **修改**：只有明确指定 `update` 才允许修改已有数据。仅覆盖传入有效非空字符串的信息字段；`common_form`、`hiragana`、`meaning` 未传入或值为 `null`、空字符串、纯空白字符串时忽略，保留原值。每次更新必须提供完整的 `tags`，仅修改标签也执行更新。
- **标签**：新增和更新均必须提供非空 `tags` 数组，不接受缺失、`null`、空数组或非法编码。编码为 1～32 位英文字母、数字或下划线，区分大小写且不去空格，重复项去重。所有标签必须已存在于 `tag_tbl`。AI 找不到合适的已有标签时不要提交该单词，不得随意选择或编造标签。
- **标签替换与事务**：更新时删除该单词全部旧标签关联，再插入完整新列表，即使新旧相同也重建，不支持清空。单词与标签共同提交或回滚，每项独立事务。`create` 遇到已有词时仍校验标签，合法后整项跳过。
- **操作控制**：传入 `operation` 时必须提供合法的 `action`。此控制块不存入单词表。
- **匹配与字段范围**：按 `word` 精确匹配，包括已标记删除的记录；不修改 `word` 或记录状态。仅接受上述字段和嵌套结构，同一批次不允许重复的 `word`。
- **结果**：每项独立处理，单项失败不影响其他项。按输入顺序返回数组索引 `index`（从 0 开始）、`word` 和处理状态：`created`、`updated`、`skipped` 或 `failed`。跳过或失败时附上原因，新增信息不完整时明确指出需要补齐的字段。

新增单词的实际 MCP 调用参数：

```json
{
  "text": "[{\"word\":\"食べる\",\"common_form\":\"食べる\",\"hiragana\":\"たべる\",\"meaning\":\"吃\",\"tags\":[\"v\",\"v2\"]}]"
}
```

修改已有单词的释义，同时提供完整标签列表：

```json
{
  "text": "[{\"word\":\"食べる\",\"meaning\":\"吃；食用\",\"tags\":[\"v\",\"v2\"],\"operation\":{\"action\":\"update\"}}]"
}
```

## 单词统计

`count_word_usage(text: str)` 为使用次数加一，`count_word_miss(text: str)` 为错误次数加一。
两者均接受单词字符串数组的 JSON 字符串，实际 MCP 参数示例：

```json
{"text":"[\"食べる\",\"飲む\"]"}
```

空数组正常返回空 `results`。null、空字符串、纯空白、非字符串及非法数据库文本
逐项跳过；同批重复词仅首次出现项计数，后续项说明重复及首次下标。
有效词按原文精确匹配，不去首尾空格。不存在或已删除的单词均跳过。
不接受逗号分隔格式、word 对象或 fields 参数；对象元素作为非字符串跳过。

每批通常三条 SQL：查询单词主表、批量插入缺失的零值统计行、批量将计数加一。
只操作工具对应的统计表；写入时再次限定主表存在且未删除。
使用 autocommit，不设置跨语句或逐词事务。初始化成功而加一失败时，零值行保留。
批量写入失败则待计数项全部 failed，已过滤项仍 skipped；不自动降级逐项重试。
主表并发变化可能导致跳过或整条语句失败，不承诺跨语句快照。

返回 `results`，按原输入顺序包含零基 `index`、`word`、`status`。
updated 项的 `counts` 只包含本工具对应字段及更新后计数，skipped 和 failed 附 `reason`。
无法安全输出的 word 为 null；只有最终 RETURNING 中的记录报告成功，处理期间未更新到
的记录返回 skipped。每次成功调用均独立加一，没有请求幂等或自动重试保证。
配置、连接、初始查询失败，以及非法 JSON、非数组顶层、非标准数值等返回工具错误。

`reset_word_miss(text: str)` 使用相同的单词字符串数组输入：

```json
{"text":"[\"食べる\"]"}
```

清零仅操作已有错误计数，每词独立事务；没有记录或已经为零时跳过，不创建记录，
不修改零值行审计信息，不影响使用次数。预处理与两个计数工具一致：无效元素跳过，
重复词仅首次处理，后续项注明首次下标；空数组或全部过滤时不读取配置、不连接数据库。
成功或已有零值时返回 `counts: {"miss_count": 0}`；无统计记录时省略 counts。

各工具使用同名专属 Service 和 description，共享 `parse_word_list_text` 及结果转换能力。
预处理返回 `WordListPreprocessResult`：status 为 continue 或 stop，message 承载终止原因。
original_items 为包含 index、original_value 的 `WordListItem` 列表，pending_items 引用
其中有效且去重的同一对象，skipped_results 保留跳过原因。输入 DTO 不包含数据库实体。
执行结果与跳过结果合并后按原始 index 排序，原始输入不直接序列化。
两张统计表各自 Mapper 返回 entity，DTO 承载输入及结果。
数据库需预先存在 `word_miss_tbl` 和 `word_usage_tbl`，服务不会自动建表。

## query_words

唯一参数 `text` 是 JSON 对象字符串，可组合 `where`、`fields`、`sort`、`limit`。
以下展示解析后的对象，实际调用时需序列化为字符串传入 `text`。

| 参数 | 用途 | 省略时 |
| --- | --- | --- |
| `where` | 条件对象，各字段和同字段的多个操作均按 AND 组合 | 无额外条件 |
| `fields` | 返回字段数组 | 全部七个业务字段 |
| `sort` | 按优先级排列的 `[[字段, "asc"或"desc"]]` | 单词 ID 升序 |
| `limit` | BIGINT 范围内的正整数 | 返回全部匹配结果，不静默截断 |

| 业务字段 | 支持的筛选 |
| --- | --- |
| `word`、`hiragana`、`meaning` | 直接值相等、`in` |
| `common_form` | 直接值相等、`in`、`like` |
| `tags` | `in`，拥有任意指定编码，不推断标签层级 |
| `usage_count`、`miss_count` | 直接值相等、`in`、`gt/gte/lt/lte`；值为 BIGINT 范围内非负整数 |

除 `tags` 外均可排序，排序并列追加单词 ID 升序。筛选和排序使用的字段不必返回。
字符串原文匹配，不自动修剪空白或转换写法。相等条件直接写值，不使用 `eq` 对象。
不支持跨字段 OR、分页、聚合或调用方指定 SQL、表名和关联。

```json
{
  "where": {
    "common_form": {"like": "%食%"},
    "tags": {"in": ["v"]},
    "usage_count": {"lte": 5}
  },
  "fields": ["word", "common_form", "usage_count"],
  "sort": [["usage_count", "asc"], ["miss_count", "desc"]],
  "limit": 10
}
```

| 场景 | 解析后的请求 |
| --- | --- |
| 所有单词信息 | `{}` |
| 所有常用写法 | `{"fields":["common_form"]}` |
| 指定单词 | `{"where":{"word":{"in":["食べる","学校"]}}}` |
| 使用次数最低的 100 个 | `{"sort":[["usage_count","asc"]],"limit":100}` |
| 陌生次数最高的 100 个 | `{"sort":[["miss_count","desc"]],"limit":100}` |
| 10 个动词或名词 | `{"where":{"tags":{"in":["v","n"]}},"limit":10}` |

`like` 原样使用 PostgreSQL `LIKE`：`"食%"` 匹配开头，`"%る"` 匹配结尾，`"%食%"` 匹配包含，
`_` 匹配单个字符。不自动加通配符，不改用 `ILIKE`。反斜杠转义字面通配符，
例如 JSON `{"where":{"common_form":{"like":"%\\%"}}}` 匹配以字面 `%` 结尾的常用写法。
`in` 与 `like` 可以同时出现在 `common_form` 条件中，两者必须同时满足。

固定排除 `status_code = 'D'` 的单词，不接受状态条件覆盖。按需关联统计表，
无统计记录统一按 0 筛选、排序和返回，查询不会初始化或更新统计记录。
标签筛选使用 EXISTS，标签返回为按编码排序的数组，一词多标签不会重复或占用多条 limit。

返回 `{"results":[对象,...]}`，每项仅包含选定字段；单字段查询仍返回对象，无匹配为空数组。
不返回总数，不合并常用写法相同的不同单词。四个审计字段不开放查询。
拒绝未知字段/操作、null、重复 JSON 键、非标准数值、布尔计数/limit、重复投影/排序字段，
以及空的 fields、sort、in、字段条件对象。空对象和空 where 合法；空文本和空 LIKE 模式沿用数据库语义。
输入校验失败不访问数据库，连接或查询失败返回脱敏工具错误。

## 标签目录维护

`src/thoth/common/tags.py` 中的 `TAG_DEFINITIONS` 是唯一人工维护的完整标签目录，包含编码及中日文名称。
新增/修改与查询工具的 description 均拼接由它生成的 `TAG_OPTIONS_DESCRIPTION`，加载说明不连接数据库。
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

JSON 解析后，单词字段直接构造成 `WordEntity`，`operation` 和完整标签列表 `tags` 通过 DTO 传递。保存时先校验整批输入，再用一次查询取得已有的单词实体，随后按原顺序逐项校验标签、新增、修改或跳过。新增和修改通过 `RETURNING` 直接取得数据库保存后的实体，不增加逐词查询；新增时仍由唯一约束处理并发冲突，默认 `create` 不会覆盖已有信息。Service 管理每项事务，先更新单词取得行锁，再删除和重建标签关联，提交前发生任何错误均整项回滚。

六张表均有对应的 entity，字段名称和基础类型对应表结构。entity 只是数据容器，所有字段均允许为 `None`、默认值为 `None`，支持空对象和局部赋值，不包含非空或业务校验。JSON 输入校验和新增必填检查保留在实体之外，数据库继续负责表约束及 ID、状态和时间戳等默认值。业务层通过对象传递记录和结果，仅在 JSON 输入输出及 SQL 参数绑定边界使用字典。

- `mcp_server.py`：启动 stdio MCP 服务，加载工具注册；启动命令保持不变。
- `tools/mcp_tools.py`：统一注册所有 MCP 工具，入口仅调用对应 Service。
- `descriptions/add_update_words_descriptions.py`：AI 可见的 add_update_words 工具说明；每个工具按完整工具名独立命名说明文件。
- `service/add_update_words_service.py`：add_update_words MCP 工具专属的完整保存流程，包括解析校验、配置读取、连接管理、保存分支、并发冲突处理、单词与标签的逐项事务、响应转换和错误处理。
- `dao/` 按一张表一个 `<表名>_mapper.py` 文件组织，尚无数据访问 SQL 的表暂不创建 mapper。
- `dao/word_tbl_mapper.py`：`WordTblMapper` 封装单词查询、新增和更新 SQL 及实体行映射。
- `dao/tag_tbl_mapper.py`：`TagTblMapper` 按编码查询已有标签，返回 `TagEntity`。
- `dao/word_tag_tbl_mapper.py`：`WordTagTblMapper` 按单词 ID 删除关联、批量插入 `WordTagEntity`。所有 Mapper 均不管理事务或决定业务分支。
- `entity/`：六张表各自的实体定义，不承担校验。
- `dto/word.py`：单词输入、逐项结果、批次结果和 DAO 保存结果。
- `service/query_words_service.py`：解析、校验、执行及序列化查询；查询记录通过各表实体与结果 DTO 传递。
- `utils/sql_query_builder.py`：独立构建 SQL 模板和参数，不连接数据库；Mapper 提供字段白名单、关联及固定条件。
- `utils/json_utils.py`：JSON 重复键与非标准数值检查等通用辅助函数。
- `db/connection.py`：数据库连接的建立、关闭及连接错误转换。
- `common/`：运行配置及各模块共用的公共定义与能力；`common/config.py` 保存数据库和操作者配置。

数据库读取和 RETURNING 不包含业务未使用的四个审计字段；实体中这些字段保持 None，数据库审计写入行为不变。

执行测试：

```shell
.venv/bin/python -m pytest
```


# 常用命令

以下命令在项目根目录执行，使用已安装项目依赖的 `.venv`。

## 启动 MCP

先在现有配置中设置 `THOTH_PG_DSN`，指向已有的 PostgreSQL 单词库。可选的 `THOTH_OPERATOR` 默认值为 `THOTH_MCP`。环境变量优先于项目根目录的 `.env`。

```shell
.venv/bin/python -m thoth.mcp_server
```

服务通过 stdio 提供 `add_update_words`、`count_word_usage`、`count_word_miss`、`reset_word_miss` 和 `query_words`，参数均为 `text: str`。配置 MCP 客户端时，将命令设为项目 `.venv/bin/python` 的绝对路径，参数设为：

```json
["-m", "thoth.mcp_server"]
```

数据库中应已存在 `word_tbl`、`word_sts_tbl`、`tag_tbl`、`word_tag_tbl`，标签字典需事先维护；启动服务不会执行建表、扩展安装或账号权限变更。

## 执行测试

```shell
.venv/bin/python -m pytest
```

## PostgreSQL 集成测试

单元测试不需要数据库。真实查询、并发、事务回滚和审计验证使用专用测试库：
在项目根目录 `.env` 或运行环境中设置 `THOTH_TEST_PG_DSN`，指向独立数据库 `thoth_test`，再执行
`.venv/bin/python -m pytest tests/integration`。
进程环境变量优先于 `.env`，不会回退使用业务连接 `THOTH_PG_DSN`。
每次连接会先确认实际数据库名为 `thoth_test`，确认后才允许写入。
测试会在测试库中创建随机独立 schema，完成后删除该 schema；
测试账号需要创建 schema 的权限。未设置测试 DSN 时，这组测试明确标记为跳过。
