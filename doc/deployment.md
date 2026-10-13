# Thoth Docker 部署操作手册

本方案把 Python、运行依赖和 MCP 程序一起放进 Docker 镜像，由 Docker 持续运行服务。
「日本語」项目通过 `http://127.0.0.1:8000/mcp` 调用服务。正式运行不需要在宿主机安装 wheel、创建虚拟环境或管理版本目录。

```text
日本語项目 → HTTP /mcp → Docker 中的 Thoth → 已有 PostgreSQL
```

源码直接复制进镜像，依赖由 `uv.lock` 固定。真实配置不进入构建上下文或镜像，启动时单独只读挂载。
配置目录变量 `THOTH_CONFIG_DIR` 保留，用来告诉容器去 `/config` 读取配置；数据库名称由连接串决定。

每个 shell 代码块是一条完整命令，按顺序在同一个 macOS 终端窗口执行，报错时先停止处理。配置代码块是文件内容，不在终端执行。

## 1. 确认 Docker Desktop 已运行

先打开 Docker Desktop，等待引擎启动。然后进入项目目录：

```shell
cd /Users/ethan/Documents/IDE_Workspace/AI_agents/thoth
```

确认 Docker 引擎能响应；失败时先处理 Docker Desktop：

```shell
docker info
```

确认 Docker Compose 可用：

```shell
docker compose version
```

后续所有 Compose 命令显式使用 `--env-file /dev/null`，避免 Compose 自动读取开发用的 `.env`。容器环境选择已在 `compose.yaml` 中明确设置为 `prd`。

## 2. 手动准备生产配置

用文本编辑器打开或创建项目根目录的 `.env.prd`：

```text
/Users/ethan/Documents/IDE_Workspace/AI_agents/thoth/.env.prd
```

把下面这一行粘贴到文件里，替换账号、密码和数据库名称。已有配置时手动编辑原文件，不要直接覆盖真实凭证。

```dotenv
THOTH_PG_DSN=postgresql://YOUR_USER:YOUR_PASSWORD@host.docker.internal:12001/YOUR_DATABASE
```

开发配置的地址是 `localhost:12001`。在 Docker Desktop 容器中，`localhost` 指容器自身，因此改成 `host.docker.internal:12001` 来访问 Mac 上发布的 PostgreSQL 端口。
若 PostgreSQL 在远程服务器，改用它真实的主机和端口。`YOUR_DATABASE` 填实际正式库名，例如 `thoth_prd`，程序不限制名称。
用户名或密码中的 `@`、`:`、`/`、`#`、`%` 等 URL 特殊字符需要进行百分号编码；SSL 等参数按数据库要求填写。

不需要创建额外的正式 `.env`：Compose 已设置 `THOTH_ENV=prd` 和 `THOTH_OPERATOR=THOTH_MCP`，只挂载 `.env.prd`。
真实文件不提交 Git。源码中的 `.env.prd.example` 是可参考的脱敏模板。

## 3. 确认数据库已准备好

在你自己的数据库客户端连接正式库，执行下面这一条只读 SQL，核对目标数据库：

```sql
SELECT current_database();
```

执行下面这一条只读 SQL，确认七张表存在（整个代码块是一条 SQL）：

```sql
SELECT name, to_regclass(name) AS existing_table
FROM unnest(ARRAY[
  'user_tbl', 'word_tbl', 'word_sts_tbl', 'tag_tbl',
  'word_tag_tbl', 'word_usage_tbl', 'word_miss_tbl'
]) AS tables(name);
```

查看已有用户名：

```sql
SELECT username FROM user_tbl ORDER BY id;
```

查看标签是否已初始化：

```sql
SELECT count(*) AS tag_count FROM tag_tbl;
```

用户名尚不存在时，才执行下面这一条 SQL（按需替换 `ethan`）：

```sql
INSERT INTO user_tbl (username) VALUES ('ethan')
ON CONFLICT (username) DO NOTHING;
```

镜像不包含数据库，也不创建或迁移表。已有数据时不要执行 `sql/rebuild_all.sql`，它会清空并重建七张表。
只有确认是允许清空的全新目标库，才手动用该脚本初始化表和字典；缺表但需要保留数据时，应另行迁移。

## 4. 构建镜像

执行这条命令，根据 Dockerfile 构建 `thoth:local` 镜像。首次构建需要联网下载基础镜像和 Python 依赖：

```shell
docker compose --env-file /dev/null build
```

Dockerfile 使用多阶段构建，只把运行依赖和源码放入最终镜像；不会安装 OpenAI SDK、pgvector 或 pytest。
`.dockerignore` 仅放行源码及构建元数据，排除真实配置、Git、本机虚拟环境、旧安装包和敏感目录。
这一步不读取生产配置内容，也不连接数据库。

## 5. 启动容器并检查状态

后台启动服务，终端退出后服务仍运行；缺少 `.env.prd` 文件时启动会报错：

```shell
docker compose --env-file /dev/null up -d
```

查看状态和端口映射：

```shell
docker compose --env-file /dev/null ps
```

查看最近的启动日志：

```shell
docker compose --env-file /dev/null logs --tail=50 thoth
```

容器监听 `0.0.0.0:8000`，宿主机仅发布 `127.0.0.1:8000`，没有配置远程用户认证，因此保持本机访问。
Host/Origin 检查仅接受本机地址。不要把端口映射改成对外公开地址来直接提供公网服务。
`healthy` 只代表 HTTP 监听进程存活，不代表数据库配置、权限或表结构已验证；第 7 步查询成功后才能确认业务可用。
`restart: unless-stopped` 会在 Docker 引擎运行时恢复服务；Mac 重启后仍需要 Docker Desktop 启动。

## 6. 在「日本語」项目配置 HTTP MCP

用文本编辑器打开或创建下面这个文件；没有 `.codex` 文件夹时先手动创建：

```text
/Users/ethan/Documents/Japanese/.codex/config.toml
```

将下面整块配置粘贴到文件中：

```toml
[mcp_servers.thoth]
url = "http://127.0.0.1:8000/mcp"
```

如果已有同名 thoth 配置，替换整个旧 thoth 配置块，并删除旧的 `[mcp_servers.thoth.env]` 块；保留其他服务设置。
HTTP 配置不再使用 `command`、`args`、`cwd` 或数据库环境变量。旧全局配置中若也存在同名 thoth，清除它的旧启动字段，避免配置合并后冲突。

现在由 Docker 负责启动和运行 MCP，Codex 只负责通过 URL 连接。这个地址是 MCP 协议端点，不是给浏览器浏览的普通网页。
Codex 需信任该项目才能加载项目配置；保存后重启应用，在「日本語」项目新建聊天。

## 7. 验证 HTTP 工具及数据库

在新聊天中发送下面这句话，进行只读验证：

> 使用 thoth 的 query_users 查询已有用户，只执行查询，不修改数据。

成功返回用户名表示 HTTP MCP、生产配置、数据库连接和用户表查询都已正常工作。

再发送下面这句话，用户名替换为第 3 步确认的实际用户名：

> 使用 thoth 的 query_words，为用户名 ethan 查询最多 5 个单词，只执行查询。

对应参数为 `{"username":"ethan","query":{"limit":5}}`。空词库返回空数组正常。
查询成功后，就可以在日语项目使用该 MCP；开发源码后续修改不会影响当前镜像中的程序。

## 8. 更新、重启与停止

修改代码后，重新构建镜像：

```shell
docker compose --env-file /dev/null build
```

使用新镜像重新创建服务：

```shell
docker compose --env-file /dev/null up -d --force-recreate
```

只修改 `.env.prd` 后，也使用上面这条重新创建命令，让容器重新挂载文件并清除进程内的配置缓存，不需要重新构建镜像。

临时停止服务：

```shell
docker compose --env-file /dev/null stop
```

重新启动已停止的服务：

```shell
docker compose --env-file /dev/null up -d
```

删除本项目的服务容器和 Compose 网络：

```shell
docker compose --env-file /dev/null down
```

本 Compose 没有定义 PostgreSQL 服务或数据库数据卷，以上命令不会删除已有数据库或本地 `.env.prd`。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| Docker 引擎连接失败 | 打开 Docker Desktop，等待引擎启动。 |
| 宿主机 8000 端口占用 | 停止占用它的开发 HTTP 服务，或把 Compose 左侧端口改为 `127.0.0.1:8001:8000`，客户端 URL 同步改为 8001。 |
| 挂载文件不存在 | 手动创建项目根目录的 `.env.prd`，确认不是 `.env.prd.txt`。 |
| 数据库连接失败 | 检查使用的是 `host.docker.internal`、宿主机端口、正确账号密码和库名，并确认数据库可接受该连接。 |
| 用户不存在 | 核对数据库中已有用户名，大小写和中文必须一致。 |
| 工具没有出现 | 核对项目受信任、URL 为 `/mcp`、容器在运行，并清理旧的 stdio 配置后重启 Codex。 |
| 浏览器打开端点报错 | MCP 需要协议请求头和握手，用第 7 步的 MCP 客户端调用验证。 |

## 本机开发环境维护（不影响 Docker 部署）

Docker 构建不使用宿主机的 `.venv`。如果旧依赖卸载后出现 `METADATA` 缺失、目录无法删除等错误，可以重建本机开发环境：

1. 停止使用开发虚拟环境的 Python 进程。
2. 在 Finder 中显示隐藏文件，删除本项目的 `.venv` 文件夹（仅包含本机 Python 环境，不是 `src` 源码，也不是 `.env` 配置文件）。
3. 在项目根目录执行下面这条命令，按当前锁文件重建环境：

```shell
uv sync --locked
```

重建完成后运行单元测试：

```shell
.venv/bin/python -m pytest tests/unit --ignore=.env.prd --ignore=secrets
```

参考：[FastMCP 官方 HTTP 部署说明](https://github.com/PrefectHQ/fastmcp/blob/main/docs/deployment/http.mdx)、[Codex MCP 配置说明](https://developers.openai.com/codex/mcp/)。
