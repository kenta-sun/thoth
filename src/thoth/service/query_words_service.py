"""查询业务服务：接收内部查询 DTO，按用户隔离统计并调用 Mapper，不处理 MCP 协议。"""

import psycopg
from thoth.service.user_lookup_service import validate_username, require_user
from thoth.common.config import get_settings
from thoth.dao.word_tbl_mapper import WordTblMapper
from thoth.db.connection import DatabaseError, open_connection
from thoth.dto.query_words import QueryRequest, QueryWordResult


def query_words(request: QueryRequest, username: str) -> list[QueryWordResult]:
    """查询未删除单词的业务结果，缺失统计按零参与查询，不产生数据库写入。

    Args:
        request: 入口转换后的内部查询 DTO；limit 为 None 表示不限数量。
        username: 已有用户名，精确匹配，不存在时拒绝查询。

    Returns:
        按请求排序的关联实体结果，未投影字段不从数据库读取。

    Raises:
        ValueError: 用户名或查询能力不合法。
        DatabaseError: 配置、连接或查询失败，驱动详情已脱敏。
    """
    validate_username(username)
    try:
        with open_connection(get_settings()) as connection:
            user = require_user(connection, username)
            return WordTblMapper(connection).query_words(request, user_id=user.id)
    except psycopg.Error as exc:
        code = f"（SQLSTATE {exc.sqlstate}）" if exc.sqlstate else ""
        raise DatabaseError(f"查询单词失败{code}。") from exc
