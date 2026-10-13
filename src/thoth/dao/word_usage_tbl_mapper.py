"""DAO 层：封装 word_usage_tbl 批量初始化、加一及实体映射。"""

import psycopg
from psycopg.rows import class_row

from thoth.entity import WordUsageEntity


class WordUsageTblMapper:
    """负责统计记录读写；批量计数使用调用方提供的 autocommit 连接。"""

    def __init__(self, connection: psycopg.Connection) -> None:
        """复用 Service 提供的连接，不管理跨语句事务。"""
        self._connection = connection

    def initialize_many(self, entities: list[WordUsageEntity], *, user_id: int) -> None:
        """按用户及实体关联 ID 批量插入零值；已有记录不变，空列表不执行 SQL。

        user_id 限定本次统计归属；审计字段使用当前数据库账号；重新检查主表状态，驱动错误向上传递。
        """
        if not entities:
            return
        # 有效主表记录才允许初始化；冲突时保留原计数和全部审计信息。
        sql = """
        INSERT INTO word_usage_tbl (user_id, word_id, usage_count, created_by, updated_by)
        SELECT %(user_id)s, id, 0, CURRENT_USER, CURRENT_USER FROM word_tbl
        WHERE id = ANY(%(ids)s) AND status_code <> 'D'
        ORDER BY id
        ON CONFLICT (user_id, word_id) DO NOTHING
        """
        with self._connection.cursor() as cursor:
            cursor.execute(sql, {"user_id": user_id, "ids": [entity.word_id for entity in entities]})

    def increment_many(self, entities: list[WordUsageEntity], *, user_id: int) -> list[WordUsageEntity]:
        """按用户及实体关联 ID 一次加一并返回实际更新实体；空列表返回空列表。

        user_id 限定统计归属；只更新仍存在且未删除的单词；SQL 失败时整条语句回滚，初始化不会撤销。
        """
        if not entities:
            return []
        # 每行使用数据库当前计数递增；RETURNING 仅报告实际更新，不承诺跨语句快照。
        sql = """
        UPDATE word_usage_tbl
        SET usage_count = usage_count + 1,
            updated_at = CURRENT_TIMESTAMP, updated_by = CURRENT_USER
        WHERE user_id = %(user_id)s AND word_id = ANY(%(ids)s)
          AND EXISTS (SELECT 1 FROM word_tbl
                      WHERE id = word_usage_tbl.word_id AND status_code <> 'D')
        RETURNING user_id, word_id, usage_count
        """
        with self._connection.cursor(row_factory=class_row(WordUsageEntity)) as cursor:
            cursor.execute(sql, {"user_id": user_id, "ids": [entity.word_id for entity in entities]})
            return cursor.fetchall()

