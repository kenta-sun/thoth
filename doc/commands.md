

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

前置：启用 pgvector、pgroonga 扩展（每个数据库只需执行一次）

```sql
-- 向量
CREATE EXTENSION IF NOT EXISTS vector;
-- 混合语种倒排索引
CREATE EXTENSION IF NOT EXISTS pgroonga;
```

创建仅供MCP服务使用的账号

```sql
CREATE ROLE thoth_mcp
    LOGIN PASSWORD '123456'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE thoth_memory TO thoth_mcp;
GRANT USAGE ON SCHEMA public TO thoth_mcp;

GRANT SELECT, INSERT, UPDATE, DELETE
ON ALL TABLES IN SCHEMA public
TO thoth_mcp;

GRANT USAGE
ON ALL SEQUENCES IN SCHEMA public
TO thoth_mcp;
```