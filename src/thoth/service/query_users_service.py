"""query_users 专属服务：读取已有用户并返回用户名列表，不写入数据库。"""

import psycopg
from thoth.dto.user import UserNameResult
from thoth.common.config import get_settings
from thoth.db.connection import DatabaseError, open_connection
from thoth.dao.user_tbl_mapper import UserTblMapper


def query_users() -> list[UserNameResult]:
    """按 ID 升序列出用户名；无用户返回空 results，配置或数据库失败抛出脱敏的 DatabaseError。"""
    try:
        with open_connection(get_settings()) as connection:
            users = UserTblMapper(connection).find_all()
        return [UserNameResult(username=user.username) for user in users]
    except psycopg.Error as exc:
        raise DatabaseError("查询用户失败。") from exc
