# 构建阶段按锁文件安装运行依赖，不安装开发测试依赖。
FROM ghcr.io/astral-sh/uv:0.11.16 AS uv
FROM python:3.11-slim-bookworm AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

# 运行阶段直接运行容器内的源码，不要求宿主机安装 Python 包。
FROM python:3.11-slim-bookworm AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8000
COPY --from=dependencies /app/.venv /app/.venv
COPY src/thoth /app/src/thoth
# 生产配置随镜像打包，修改配置后重新构建镜像。
COPY .env.prd /app/.env.prd
EXPOSE 8000
# 仅检查监听进程存活，不读取配置或查询数据库。
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=3).close()"]
CMD ["python", "-m", "thoth.mcp_server"]
