"""DAO 层：只读查询用户表，供工具列出用户名及 Service 校验统计归属。"""

import psycopg
from psycopg.rows import class_row
from thoth.entity import UserEntity


class UserTblMapper:
    """查询用户记录，不提供用户新增、修改或删除能力。"""

    def __init__(self, connection: psycopg.Connection) -> None:
        """复用业务层连接，不管理事务。"""
        self._connection = connection

    def find_by_username(self, username: str) -> UserEntity | None:
        """按区分大小写的原文查找用户；不存在返回 None。"""
        with self._connection.cursor(row_factory=class_row(UserEntity)) as cursor:
            cursor.execute("SELECT id, username FROM user_tbl WHERE username = %(username)s",
                           {"username": username})
            return cursor.fetchone()

    def find_all(self) -> list[UserEntity]:
        """按用户 ID 升序返回全部用户；无记录返回空列表。"""
        with self._connection.cursor(row_factory=class_row(UserEntity)) as cursor:
            cursor.execute("SELECT id, username FROM user_tbl ORDER BY id")
            return cursor.fetchall()
