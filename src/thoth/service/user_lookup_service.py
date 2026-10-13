"""共享业务层：校验用户名并查询已有用户，供各工具限定统计归属。"""

import psycopg
from thoth.dao.user_tbl_mapper import UserTblMapper
from thoth.db.connection import DatabaseError
from thoth.entity import UserEntity


def validate_username(username: str) -> None:
    """用户名须为 1～128 字符且无首尾空白；非法值抛出 ValueError，不修剪原文。"""
    if not isinstance(username, str) or not 1 <= len(username) <= 128 or username != username.strip():
        raise ValueError("username 必须为 1～128 个字符，且不能包含首尾空白。")
    try:
        username.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("username 包含无法存储的字符。") from None
    if "\x00" in username:
        raise ValueError("username 包含无法存储的字符。")


def require_user(connection: psycopg.Connection, username: str) -> UserEntity:
    """查询已有用户；不存在抛出 ValueError，数据库异常脱敏，不自动创建用户。"""
    validate_username(username)
    try:
        user = UserTblMapper(connection).find_by_username(username)
    except psycopg.Error as exc:
        raise DatabaseError("查询用户失败。") from exc
    if user is None:
        raise ValueError("用户不存在，请先手动通过 SQL 添加用户。")
    if user.id is None:
        raise DatabaseError("用户记录未返回有效 ID。")
    return user
