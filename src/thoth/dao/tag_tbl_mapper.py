"""DAO 层标签字典查询：向 Service 返回标签实体，不校验业务或管理事务。"""

from __future__ import annotations

import psycopg
from psycopg.rows import class_row

from thoth.entity import TagEntity


class TagTblMapper:
    """封装 tag_tbl 查询，复用调用方的连接及事务。"""

    def __init__(self, connection: psycopg.Connection) -> None:
        """绑定 Service 提供的连接，不建立或关闭连接。"""
        self._connection = connection

    def find_by_codes(self, codes: list[str]) -> list[TagEntity]:
        """返回编码匹配的标签实体；空集合不查询，缺失编码不会出现在结果中，驱动异常向上传递。"""
        if not codes:
            return []
        # 按编码精确查询已有标签，不创建标签；关联写入时仍由外键保证引用有效。
        sql = """
        SELECT code, zh_name, jp_name
        FROM tag_tbl
        WHERE code = ANY(%(codes)s)
        """
        # class_row 按查询列名构造 TagEntity，供业务层读取标签编码。
        with self._connection.cursor(row_factory=class_row(TagEntity)) as cursor:
            cursor.execute(sql, {"codes": codes})
            return cursor.fetchall()
