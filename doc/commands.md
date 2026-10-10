

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
