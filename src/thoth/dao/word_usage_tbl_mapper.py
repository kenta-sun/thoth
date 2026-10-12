"""DAO 层：封装 word_usage_tbl 批量初始化、加一及实体映射。"""

import psycopg
from psycopg.rows import class_row

from thoth.entity import WordUsageEntity


class WordUsageTblMapper:
    """负责统计记录读写；批量计数使用调用方提供的 autocommit 连接。"""

    def __init__(self, connection: psycopg.Connection) -> None:
        """复用 Service 提供的连接，不管理跨语句事务。"""
        self._connection = connection

    def initialize_many(self, entities: list[WordUsageEntity], *, operator: str) -> None:
        """按实体关联 ID 批量插入零值；已有记录不变，空列表不执行 SQL。

        operator 填充新增审计字段；重新检查主表状态，驱动错误向上传递。
        """
        if not entities:
            return
        # 有效主表记录才允许初始化；冲突时保留原计数和全部审计信息。
        sql = """
        INSERT INTO word_usage_tbl (word_id, usage_count, created_by, updated_by)
        SELECT id, 0, %(operator)s, %(operator)s FROM word_tbl
        WHERE id = ANY(%(ids)s) AND status_code <> 'D'
        ORDER BY id
        ON CONFLICT (word_id) DO NOTHING
        """
        with self._connection.cursor() as cursor:
            cursor.execute(sql, {"ids": [entity.word_id for entity in entities], "operator": operator})

    def increment_many(self, entities: list[WordUsageEntity], *, operator: str) -> list[WordUsageEntity]:
        """按实体关联 ID 一次加一并返回实际更新实体；空列表返回空列表。

        只更新仍存在且未删除的单词；SQL 失败时整条语句回滚，初始化不会撤销。
        """
        if not entities:
            return []
        # 每行使用数据库当前计数递增；RETURNING 仅报告实际更新，不承诺跨语句快照。
        sql = """
        UPDATE word_usage_tbl
        SET usage_count = usage_count + 1,
            updated_at = CURRENT_TIMESTAMP, updated_by = %(operator)s
        WHERE word_id = ANY(%(ids)s)
          AND EXISTS (SELECT 1 FROM word_tbl
                      WHERE id = word_usage_tbl.word_id AND status_code <> 'D')
        RETURNING word_id, usage_count, created_at, updated_at, created_by, updated_by
        """
        with self._connection.cursor(row_factory=class_row(WordUsageEntity)) as cursor:
            cursor.execute(sql, {"ids": [entity.word_id for entity in entities], "operator": operator})
            return cursor.fetchall()

