"""DAO 层：按用户和单词读写当前熟悉度，事务及状态校验由写入 Service 管理。"""

import psycopg
from psycopg.rows import class_row

from thoth.entity import WordFamEntity


class WordFamTblMapper:
    """封装熟悉度关联表，不修改单词内容或其他用户记录。"""

    def __init__(self, connection: psycopg.Connection) -> None:
        """复用调用方事务连接，不自行提交。"""
        self._connection = connection

    def find_for_update(self, *, user_id: int, word_id: int) -> WordFamEntity | None:
        """锁定指定用户和单词的记录；尚未评定返回 None。"""
        with self._connection.cursor(row_factory=class_row(WordFamEntity)) as cursor:
            cursor.execute(
                "SELECT user_id, word_id, tag_code FROM word_fam_tbl "
                "WHERE user_id = %(user_id)s AND word_id = %(word_id)s FOR UPDATE",
                {"user_id": user_id, "word_id": word_id},
            )
            return cursor.fetchone()

    def save(self, entity: WordFamEntity) -> None:
        """新增或更新唯一熟悉度记录；调用方持有单词行锁，外键错误向上传递。"""
        # 联合主键处理并发新增；相同编码不改审计字段，创建信息始终保留。
        sql = """
        INSERT INTO word_fam_tbl (user_id, word_id, tag_code)
        VALUES (%(user_id)s, %(word_id)s, %(tag_code)s)
        ON CONFLICT (user_id, word_id) DO UPDATE
        SET tag_code = EXCLUDED.tag_code,
            updated_at = CURRENT_TIMESTAMP, updated_by = CURRENT_USER
        WHERE word_fam_tbl.tag_code IS DISTINCT FROM EXCLUDED.tag_code
        """
        with self._connection.cursor() as cursor:
            cursor.execute(sql, {"user_id": entity.user_id, "word_id": entity.word_id,
                                 "tag_code": entity.tag_code})
