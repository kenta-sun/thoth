"""数据库基础层负责按配置建立 PostgreSQL 连接，并在调用结束时关闭。

MCP 入口通过 open_connection 获取连接后交给仓储；连接启用 autocommit，
每项写入的事务范围由仓储显式管理。本模块不加载扩展，也不执行结构变更。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from thoth.config import Settings, get_settings


class DatabaseError(RuntimeError):
    """承载可对外展示的数据库错误消息，供业务层区分逐项失败或整批失败。

    抛出位置负责避免在消息中包含连接凭证、原始 SQL 或参数；
    通过异常链关联的驱动错误仅用于内部诊断，不属于对外消息。
    """


@contextmanager
def open_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    """提供已启用 autocommit 的连接，并保证离开上下文时关闭连接。

    调用方上下文内产生的异常会继续向上传递，连接仍在 finally 中关闭。

    Args:
        settings: 本次连接所用配置；为 None 时调用配置层读取并校验配置。

    Yields:
        打开的 PostgreSQL 连接，驱动连接超时设为 5 秒。调用方负责具体查询，
        仓储用显式事务管理每项写入，本上下文不额外包裹整批事务。

    Raises:
        ValueError: 未提供 settings 且配置层校验失败，原样交给入口处理。
        DatabaseError: 建立连接时发生驱动错误，转换为不含连接详情的消息。
    """
    # 显式传入配置时直接复用；配置错误不混同为数据库连接错误。
    resolved = settings or get_settings()
    try:
        # autocommit 使查重读取不留下跨项事务；写入事务由仓储逐项开启。
        connection = psycopg.connect(
            resolved.pg_dsn, autocommit=True, connect_timeout=5
        )
    except psycopg.Error as exc:
        # 只在建立连接的边界转换错误；对外文字不拼接 DSN 或驱动原始消息。
        raise DatabaseError(
            "连接 PostgreSQL 失败，请检查 THOTH_PG_DSN、数据库服务及访问权限。"
        ) from exc

    try:
        yield connection
    finally:
        # 无论调用方正常完成还是抛出异常，均释放连接资源。
        connection.close()
