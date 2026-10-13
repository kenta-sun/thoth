# Thoth 正式部署操作手册

目标：开发继续使用 thoth 源码目录；「日本語」项目调用独立安装的稳定版本，连接你配置的正式数据库（本文以 `thoth_memory` 为例，名称可自定义）。
MCP 使用 stdio，由 Codex 启动本地进程，不需要额外开启 HTTP 服务、购买服务器或发布到 PyPI。

以下命令按当前电脑路径编写，在 macOS 终端逐块执行。任何一步报错，都先停在该步处理，成功后再继续。
文件内容使用文本编辑器填写；不要将密码直接写进终端命令。本文中的 `YOUR_USER`、`YOUR_PASSWORD` 必须替换。

## 1. 确认工具与正式数据库

```shell
cd /Users/ethan/Documents/IDE_Workspace/AI_agents/thoth
uv --version
.venv/bin/python --version
```

当前开发环境已有 uv 和 Python 3.11。下文沿用该 Python 创建独立虚拟环境；它依赖本机的基础 Python，升级时不要删除正在使用的基础 Python。

开发配置使用 `localhost:12001/thoth_dev`。如果正式库也在同一个 PostgreSQL 实例，正式连接使用 `localhost:12001/thoth_memory`；若正式库在另一台机器，后面同时修改主机和端口。
打包安装不会创建数据库，也不会复制开发数据。

在你自己的数据库客户端选择正式库，手动执行以下只读 SQL：

```sql
SELECT current_database();
SELECT name, to_regclass(name) AS existing_table
FROM unnest(ARRAY[
  'user_tbl', 'word_tbl', 'word_sts_tbl', 'tag_tbl',
  'word_tag_tbl', 'word_usage_tbl', 'word_miss_tbl'
]) AS tables(name);
```

第一个结果应是你准备使用的正式数据库名称（本文示例为 `thoth_memory`），第二个结果的七张表都应该存在。已有正式数据时保留原库，不执行重建脚本；缺表或结构不匹配时先单独处理数据库迁移，再继续安装。

只有你确认这是全新、允许清空的目标库时，才可手动执行项目中的 `sql/rebuild_all.sql` 初始化。
**该脚本会删除并重建七张表，已有数据会被清空；它不是日常安装或升级步骤。**

表准备好后，手动确认用户和标签：

```sql
SELECT username FROM user_tbl ORDER BY id;
SELECT count(*) AS tag_count FROM tag_tbl;
```

标签应已初始化。用户名不存在时，可执行以下语句（需要其他用户名时替换 `ethan`）：

```sql
INSERT INTO user_tbl (username) VALUES ('ethan')
ON CONFLICT (username) DO NOTHING;
```

## 2. 验证代码、打包并导出固定版本依赖

```shell
cd /Users/ethan/Documents/IDE_Workspace/AI_agents/thoth
uv sync --locked
.venv/bin/python -m pytest tests/unit --ignore=.env.prd --ignore=secrets
uv build --wheel --out-dir dist
uv export --locked --no-dev --no-emit-project --output-file dist/requirements.lock.txt --quiet
```

当前版本产物是 `dist/thoth-0.1.0-py3-none-any.whl` 和 `dist/requirements.lock.txt`。
前者包含程序，后者从 `uv.lock` 导出正式运行依赖及校验哈希，不包含 pytest 和源码的可编辑安装引用。
运行依赖仍使用项目原有列表，没有为部署额外增加依赖。wheel 不包含 `.env`、真实凭证或数据库数据；SQL 文件保留在源码项目，手动维护数据库时使用。

## 3. 创建正式目录并安装程序

```shell
mkdir -p /Users/ethan/.local/share/thoth/config
mkdir -p /Users/ethan/.local/share/thoth/releases/0.1.0
chmod 700 /Users/ethan/.local/share/thoth/config
cp /Users/ethan/Documents/IDE_Workspace/AI_agents/thoth/dist/thoth-0.1.0-py3-none-any.whl /Users/ethan/.local/share/thoth/releases/0.1.0/
cp /Users/ethan/Documents/IDE_Workspace/AI_agents/thoth/dist/requirements.lock.txt /Users/ethan/.local/share/thoth/releases/0.1.0/
uv venv /Users/ethan/.local/share/thoth/releases/0.1.0/.venv --python /Users/ethan/Documents/IDE_Workspace/AI_agents/thoth/.venv/bin/python
uv pip sync --python /Users/ethan/.local/share/thoth/releases/0.1.0/.venv/bin/python /Users/ethan/.local/share/thoth/releases/0.1.0/requirements.lock.txt --require-hashes
uv pip install --python /Users/ethan/.local/share/thoth/releases/0.1.0/.venv/bin/python --no-deps /Users/ethan/.local/share/thoth/releases/0.1.0/thoth-0.1.0-py3-none-any.whl
uv pip check --python /Users/ethan/.local/share/thoth/releases/0.1.0/.venv/bin/python
```

该步骤仅用于首次安装此版本。若此版本目录已在使用，不在里面反复重建虚拟环境；升级用新版本目录，见文末。
依赖同步必须在安装 wheel 之前执行，因为 `uv pip sync` 会移除依赖清单之外的包，包括已经安装的 thoth。

## 4. 手动填写正式配置

配置目录固定为 `/Users/ethan/.local/share/thoth/config`。在该目录手动创建以下两个隐藏文件。
Finder 可用 `Command + Shift + G` 输入目录，再用 `Command + Shift + .` 显示隐藏文件。
文本编辑器保存为纯文本，确保没有多加 `.txt` 后缀。

文件一：`/Users/ethan/.local/share/thoth/config/.env`

```dotenv
THOTH_ENV=prd
THOTH_OPERATOR=THOTH_MCP
```

文件二：`/Users/ethan/.local/share/thoth/config/.env.prd`

```dotenv
THOTH_PG_DSN=postgresql://YOUR_USER:YOUR_PASSWORD@localhost:12001/thoth_memory
```

这份模板参照开发配置的字段、主机和端口，数据库名称以 `thoth_memory` 为例；请改为你的实际正式库名，程序不限制名称。
使用有正式库访问权限的数据库账号和密码，不要把连接串写进公共 `.env`。
如果用户名或密码包含 `@`、`:`、`/`、`#`、`%` 等 URL 特殊字符，需对用户名或密码部分进行 URL 百分号编码。
如正式服务要求 SSL 等连接参数，应沿用正式数据库提供的要求。

仓库根目录的 `.env.prd` 不会被这套部署读取；这里使用的是独立正式目录。配置文件由你手动创建和维护，不放入 wheel 或 Git。
`THOTH_CONFIG_DIR` 在第 6 步的 MCP 配置中设置，不写进上述两个文件。

保存后执行：

```shell
chmod 600 /Users/ethan/.local/share/thoth/config/.env /Users/ethan/.local/share/thoth/config/.env.prd
```

## 5. 检查安装位置和配置加载

以下命令只检查安装与配置，不连接数据库，不输出连接串：

```shell
env -u THOTH_PG_DSN -u THOTH_OPERATOR -u PYTHONPATH THOTH_ENV=prd THOTH_CONFIG_DIR=/Users/ethan/.local/share/thoth/config /Users/ethan/.local/share/thoth/releases/0.1.0/.venv/bin/python -I - <<'PY'
from importlib.metadata import version
from pathlib import Path
import thoth
from thoth.common.config import get_settings

settings = get_settings()
print("版本:", version("thoth"))
print("安装位置:", Path(thoth.__file__).resolve())
print("环境:", settings.environment)
print("配置加载成功；目标数据库由 THOTH_PG_DSN 指定")
PY
```

预期：版本为 `0.1.0`，安装位置在 `releases/0.1.0/.venv` 中，环境为 `prd`，并显示配置加载成功。该步骤不验证数据库连接，实际目标库在第 1 步确认，在第 7 步验证查询。
如果安装位置仍在开发源码目录，说明并未使用独立 wheel 安装，先修正再继续。

## 6. 给「日本語」项目添加 MCP 配置

```shell
mkdir -p /Users/ethan/Documents/Japanese/.codex
```

在文本编辑器中打开或新建 `/Users/ethan/Documents/Japanese/.codex/config.toml`，添加以下内容。
如果已有其他设置，保留它们；已有同名 `[mcp_servers.thoth]` 时修改原块，不重复添加。

```toml
[mcp_servers.thoth]
command = "/Users/ethan/.local/share/thoth/releases/0.1.0/.venv/bin/python"
args = ["-I", "-m", "thoth.mcp_server"]
cwd = "/Users/ethan/.local/share/thoth"

[mcp_servers.thoth.env]
THOTH_CONFIG_DIR = "/Users/ethan/.local/share/thoth/config"
THOTH_ENV = "prd"
THOTH_OPERATOR = "THOTH_MCP"
```

`-I` 使用 Python 隔离模式，避免工作目录和 `PYTHONPATH` 意外引入开发源码。
此处只记录启动方式，不放数据库密码。不要在 MCP 的 `env` 中再配置 `THOTH_PG_DSN`：进程中的连接串会优先于 `.env.prd`。
如果此前从终端给 Codex 设置过全局 `THOTH_PG_DSN`，应先取消该环境变量，再重新启动应用。

Codex 官方支持在受信任项目的 `.codex/config.toml` 中配置项目专属 MCP。此文件负责给「日本語」项目增加 thoth；已有全局 MCP 设置仍然可能同时生效。
若全局设置已经存在同名服务，检查它是否遗留连接串环境变量或其他配置，避免合并后覆盖正式配置。
参考：[官方 MCP 配置说明](https://developers.openai.com/codex/mcp/)。

## 7. 重新加载并验证只读调用

在 Codex 中打开「日本語」项目，确保该项目处于受信任状态。重新启动应用并在该项目新建聊天，以便载入新增配置。
MCP 管理页面应能看到 thoth 连接成功。无需手动在终端保持 `python -m thoth.mcp_server` 运行。

先发送：

> 使用 thoth 的 query_users 查询已有用户，只执行查询，不新增或修改数据。

应能返回第 1 步准备的用户名。工具列表出现仅表示 MCP 已启动；这次查询成功才表示生产配置、连接和用户表可以正常使用。

然后发送（用户名按实际情况替换）：

> 使用 thoth 的 query_words，为用户名 ethan 查询最多 5 个单词，只执行查询。

工具参数应为 `{"username":"ethan","query":{"limit":5}}`。空词库返回空数组也正常。
这一步能进一步验证单词、标签和统计相关查询，不写入生产数据。

## 8. 开始正式使用并记录版本

日常在「日本語」项目聊天中使用查词、保存单词和统计工具。可在该项目现有 `AGENTS.md` 中按需追加：

```text
日语词库使用 thoth MCP。我的词库用户名是 ethan。
查询词库时调用 query_words；需要确认用户时调用 query_users。
只有我明确要求保存、修改或统计单词时，才调用相应写入工具。
```

这段规则中的用户名要与数据库一致。保留 `releases/0.1.0` 目录下的 wheel、依赖锁文件和虚拟环境，便于追溯。
当前源码继续连接开发库；修改源码不会改变已安装的 wheel，修改正式配置后需重启 MCP 才生效。

## 后续升级与回退

1. 在开发项目完成修改和测试，将 `pyproject.toml` 的版本号提升（例如 `0.1.1`），运行 `uv lock` 更新锁文件。
2. 按第 2 步重新验证、打包和导出依赖，wheel 文件名随版本变为 `thoth-0.1.1-py3-none-any.whl`。
3. 按第 3 步安装到新的 `releases/0.1.1`，将命令中的版本号全部替换；保留 `releases/0.1.0`，共用已有正式配置目录。
4. 用第 5 步检查新版本，将检查命令中的 `0.1.0` 改成 `0.1.1`。
5. 将日语项目 MCP 配置里的 Python 路径改到新版本，重启并按第 7 步验证。
6. 如果新版程序有问题，将路径改回旧版并重启。此操作只回退程序，不会撤销数据库写入或数据库结构变更。

升级通常不需要修改正式凭证，也不执行 `rebuild_all.sql`。涉及数据库结构变化时，必须另行准备并验证迁移方案。

## 常见问题

| 现象 | 检查方式 |
| --- | --- |
| `THOTH_CONFIG_DIR 必须为现有目录的绝对路径` | 检查目录是否存在，填写完整 `/Users/...` 路径，不写 `~` 或相对路径。 |
| `缺少环境配置文件 .env.prd` | 检查第 4 步文件的位置及后缀，不要放到开发目录。 |
| `公共 .env 不允许配置 THOTH_PG_DSN` | 把连接串放到独立配置目录的 `.env.prd`。 |
| 连接 PostgreSQL 失败 | 检查数据库是否运行、主机端口和账号密码是否正确、账号是否有访问权限。 |
| 连接到了非预期数据库 | 检查 `.env.prd` 中的实际库名，以及是否有进程级 `THOTH_PG_DSN` 覆盖文件；运行服务不做固定库名校验。 |
| 查询提示用户不存在 | 用第 1 步 SQL 确认用户名，大小写和中文必须一致。 |
| Codex 没有出现工具 | 确认处于「日本語」项目、项目受信任、配置没有重复 TOML 表，重启后新建聊天。 |
| 依赖下载失败 | 检查网络及 uv 的包索引配置，成功完成安装和 `uv pip check` 后再继续。 |
