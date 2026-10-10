"""PostgreSQL 连接管理，不加载向量扩展，也不执行结构变更。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from thoth.config import Settings, get_settings


class DatabaseError(RuntimeError):
    """可直接向调用方展示的数据库错误，不包含连接凭证或原始 SQL。"""


@contextmanager
def open_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    resolved = settings or get_settings()
    try:
        connection = psycopg.connect(
            resolved.pg_dsn, autocommit=True, connect_timeout=5
        )
    except psycopg.Error as exc:
        raise DatabaseError(
            "连接 PostgreSQL 失败，请检查 THOTH_PG_DSN、数据库服务及访问权限。"
        ) from exc

    try:
        yield connection
    finally:
        connection.close()
