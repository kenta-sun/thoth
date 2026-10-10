# Thoth

基于 Python、FastMCP 和 PostgreSQL 的日语单词 MCP 服务。目前仅提供 `save_words(text: str)`，由 AI 整理单词信息，再通过固定业务接口写入已有的 `word_tbl`。

服务不调用大模型、不生成向量，也不向 AI 提供任意 SQL 或表结构修改接口。项目原有依赖暂时保留。

## 配置与启动

使用 Python 3.11 或更高版本，以及项目现有的虚拟环境。配置可放在项目根目录的 `.env` 中，或通过环境变量传入；环境变量优先。

| 配置项 | 说明 |
| --- | --- |
| `THOTH_PG_DSN` | 必填，PostgreSQL 连接字符串，指向已有的单词数据库。 |
| `THOTH_OPERATOR` | 可选，写入审计字段的操作者标识，默认 `THOTH_MCP`。 |

运行不需要 OpenAI API Key。服务使用已有的单词表，不自动建表、修改表结构或调整数据库账号权限。

在项目根目录启动 stdio MCP 服务：

```shell
.venv/bin/python -m thoth.mcp_server
```

MCP 客户端应使用虚拟环境中 Python 的绝对路径，启动参数为 `-m thoth.mcp_server`。相关命令见 [doc/commands.md](doc/commands.md)。

## save_words

唯一参数 `text` 为非空 JSON 数组字符串，每个元素代表一个单词。下面展示字符串解析后的结构：

```json
[
  {
    "word": "字符串；单词基本形式，每项必填且不能为空，用于精确判重和更新定位。",
    "common_form": "字符串；常用写法，新增时必填，可以与 word 相同。",
    "hiragana": "字符串；平假名读音，新增时必填。",
    "meaning": "字符串；中文释义，新增时必填。",
    "operation": {
      "action": "字符串；仅允许 create 或 update。整个 operation 可以省略，省略时默认 create。create：不存在则新增，已存在则跳过；update：不存在则新增，已存在则修改。"
    }
  }
]
```

- **新增**：`word`、`common_form`、`hiragana`、`meaning` 都必须为非空字符串；缺失、`null`、空字符串或纯空白字符串均报错。`update` 未找到已有单词时，也适用此要求。
- **修改**：只有明确指定 `update` 才允许修改已有数据。仅覆盖传入有效非空字符串的字段；`common_form`、`hiragana`、`meaning` 未传入或值为 `null`、空字符串、纯空白字符串时忽略，保留原值。没有需要修改的字段时跳过。
- **操作控制**：传入 `operation` 时必须提供合法的 `action`。此控制块不存入单词表。
- **匹配与字段范围**：按 `word` 精确匹配，包括已标记删除的记录；不修改 `word` 或记录状态。仅接受上述字段和嵌套结构，同一批次不允许重复的 `word`。
- **结果**：每项独立处理，单项失败不影响其他项。按输入顺序返回数组索引 `index`（从 0 开始）、`word` 和处理状态：`created`、`updated`、`skipped` 或 `failed`。跳过或失败时附上原因，新增信息不完整时明确指出需要补齐的字段。

新增单词的实际 MCP 调用参数：

```json
{
  "text": "[{\"word\":\"食べる\",\"common_form\":\"食べる\",\"hiragana\":\"たべる\",\"meaning\":\"吃\"}]"
}
```

仅修改已有单词的释义：

```json
{
  "text": "[{\"word\":\"食べる\",\"meaning\":\"吃；食用\",\"operation\":{\"action\":\"update\"}}]"
}
```

## 代码结构

保存时先校验整批输入，再用一次查询取得已有的 `word` 集合，随后按原顺序逐项新增、修改或跳过。不存在逐词查询；新增时仍由唯一约束处理并发冲突，默认 `create` 不会覆盖已有信息。

- `mcp_server.py`：FastMCP 工具注册、AI 可见说明和入口。
- `word_service.py`：JSON 解析、输入校验、操作选择和逐项结果整理。
- `db/word_repo.py`：固定的参数化 SQL 与单词数据访问。
- `db/connection.py`：数据库连接。
- `config.py`：数据库和操作者配置。

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

服务通过 stdio 提供 `save_words(text: str)`。配置 MCP 客户端时，将命令设为项目 `.venv/bin/python` 的绝对路径，参数设为：

```json
["-m", "thoth.mcp_server"]
```

数据库中应已存在 `word_tbl`；启动服务不会执行建表、扩展安装或账号权限变更。

## 执行测试

```shell
.venv/bin/python -m pytest
```
