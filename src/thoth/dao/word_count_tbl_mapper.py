"""DAO 层：封装 word_count_tbl 批量初始化、加一及实体映射。"""

import psycopg
from psycopg.rows import class_row

from thoth.entity import WordCountEntity


class WordCountTblMapper:
    """负责统计记录读写；批量计数使用调用方提供的 autocommit 连接。"""

    def __init__(self, connection: psycopg.Connection) -> None:
        """复用 Service 提供的连接，不管理跨语句事务。"""
        self._connection = connection

    def initialize_many(self, entities: list[WordCountEntity], *, user_id: int, count_type: str) -> None:
        """按用户及实体关联 ID 批量插入零值；已有记录不变，空列表不执行 SQL。

        user_id 与 count_type 共同限定本次统计归属；审计字段使用当前数据库账号；重新检查主表状态，驱动错误向上传递。
        """
        if not entities:
            return
        # 有效主表记录才允许初始化；冲突时保留原计数和全部审计信息。
        sql = """
        INSERT INTO word_count_tbl (user_id, word_id, count_type, count_value, created_by, updated_by)
        SELECT %(user_id)s, id, %(count_type)s, 0, CURRENT_USER, CURRENT_USER FROM word_tbl
        WHERE id = ANY(%(ids)s) AND status_code <> 'D'
        ORDER BY id
        ON CONFLICT (user_id, word_id, count_type) DO NOTHING
        """
        with self._connection.cursor() as cursor:
            cursor.execute(sql, {"user_id": user_id, "count_type": count_type, "ids": [entity.word_id for entity in entities]})

    def increment_many(self, entities: list[WordCountEntity], *, user_id: int, count_type: str) -> list[WordCountEntity]:
        """按用户及实体关联 ID 一次加一并返回实际更新实体；空列表返回空列表。

        user_id 与 count_type 共同限定统计归属；只更新仍存在且未删除的单词；SQL 失败时整条语句回滚，初始化不会撤销。
        """
        if not entities:
            return []
        # 每行使用数据库当前计数递增；RETURNING 仅报告实际更新，不承诺跨语句快照。
        sql = """
        UPDATE word_count_tbl
        SET count_value = count_value + 1,
            updated_at = CURRENT_TIMESTAMP, updated_by = CURRENT_USER
        WHERE user_id = %(user_id)s AND count_type = %(count_type)s AND word_id = ANY(%(ids)s)
          AND EXISTS (SELECT 1 FROM word_tbl
                      WHERE id = word_count_tbl.word_id AND status_code <> 'D')
        RETURNING user_id, word_id, count_type, count_value
        """
        with self._connection.cursor(row_factory=class_row(WordCountEntity)) as cursor:
            cursor.execute(sql, {"user_id": user_id, "count_type": count_type, "ids": [entity.word_id for entity in entities]})
            return cursor.fetchall()

    def find_for_update(self, word_id: int, *, user_id: int, count_type: str) -> WordCountEntity | None:
        """锁定指定用户、单词及类型的已有计数记录，供清零判断；不存在返回 None，不创建记录。"""
        sql = """
        SELECT user_id, word_id, count_type, count_value
        FROM word_count_tbl WHERE user_id = %(user_id)s AND count_type = %(count_type)s AND word_id = %(word_id)s FOR UPDATE
        """
        with self._connection.cursor(row_factory=class_row(WordCountEntity)) as cursor:
            cursor.execute(sql, {"user_id": user_id, "count_type": count_type, "word_id": word_id})
            return cursor.fetchone()

    def reset(self, entity: WordCountEntity) -> WordCountEntity | None:
        """按关联 ID 清零非零计数并返回记录；不存在或已为零返回 None。

        entity.user_id、word_id 与 count_type 共同限定更新记录；修改者由 CURRENT_USER 记录；调用方必须持有单词及统计记录的锁。
        """
        # 只更新非零记录，跳过时不触碰审计信息，保留创建信息及统计行。
        sql = """
        UPDATE word_count_tbl SET count_value = 0,
            updated_at = CURRENT_TIMESTAMP, updated_by = CURRENT_USER
        WHERE user_id = %(user_id)s AND count_type = %(count_type)s AND word_id = %(word_id)s AND count_value <> 0
        RETURNING user_id, word_id, count_type, count_value
        """
        with self._connection.cursor(row_factory=class_row(WordCountEntity)) as cursor:
            cursor.execute(sql, {"user_id": entity.user_id, "count_type": entity.count_type, "word_id": entity.word_id})
            return cursor.fetchone()
