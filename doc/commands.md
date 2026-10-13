

```shell
docker run -d \
  --name thoth-pg \
  --restart unless-stopped \
  -e POSTGRES_USER=thoth \
  -e POSTGRES_PASSWORD=123456 \
  -e POSTGRES_DB=thoth_memory \
  -p 12001:5432 \
  -v thoth_pg_data:/var/lib/postgresql/data \
  pgvector/pgvector:pg17
```

## 完整重建与用户维护

停止 MCP 后，在目标数据库的 SQL 客户端整份执行 `sql/rebuild_all.sql`。
该脚本会清空七张项目表，再创建表和初始化字典；重复执行仍会清空。
失败时停止执行并回滚。生产环境由使用者手动执行。

用户表初始为空，随后编辑并单独执行 `sql/manual/add_user.sql` 添加用户名，再启动新版 MCP。
所有原有工具调用必须提供独立的 username 字符串；query_users 无参数，只读列出用户。

```shell
.venv/bin/python -m thoth.utils.generate_rebuild_sql
.venv/bin/python -m thoth.utils.generate_rebuild_sql --check
```
