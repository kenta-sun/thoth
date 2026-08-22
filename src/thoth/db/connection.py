"""
数据库连接管理。

职责：
1. 按配置创建 psycopg 连接。
2. 在连接上注册 pgvector 的类型适配器，让 Python 的 list[float]
   能直接作为 VECTOR 参数传入、并把查询结果自动转回 Python 对象。

设计取舍：
- 不引入连接池。当前只有命令行与 MCP 单进程调用，一次提取任务内复用一条连接足够；
  等接入并发场景再换成 ``psycopg_pool.ConnectionPool``，届时只需改这一个文件。
- 关闭 autocommit，由仓储层显式控制事务边界。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector

from thoth.config import Settings, get_settings


class DatabaseError(RuntimeError):
    """
    数据库操作失败时抛出的统一异常。

    把 psycopg 的各类异常归一，避免上层依赖具体驱动的异常类型。
    """


@contextmanager
def open_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    """
    创建一条已完成 pgvector 初始化的数据库连接。

    入参：
    - settings : 运行期配置。为 None 时取全局单例配置。

    产出：
    - psycopg 连接对象。退出 with 块时自动关闭。

    异常：
    - DatabaseError：连接失败，或 pgvector 扩展未安装。

    用法：

        with open_connection() as conn:
            repo = MemoryRepository(conn)
            ...
    """
    resolved = settings or get_settings()

    try:
        connection = psycopg.connect(resolved.pg_dsn, autocommit=False)
    except psycopg.Error as exc:
        raise DatabaseError(
            f"连接 PostgreSQL 失败：{exc}\n请检查配置项 THOTH_PG_DSN 以及数据库容器是否已启动。"
        ) from exc

    try:
        # 注册向量类型。若数据库未执行 CREATE EXTENSION vector，这一步会失败，
        # 此时提前给出可操作的提示，而不是等到插入数据时才报一个含义模糊的错误。
        try:
            register_vector(connection)
        except psycopg.Error as exc:
            raise DatabaseError(
                f"注册 pgvector 类型失败：{exc}\n"
                "请先在目标数据库中执行：CREATE EXTENSION IF NOT EXISTS vector;"
            ) from exc

        yield connection
    finally:
        connection.close()
