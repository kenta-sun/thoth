"""DAO 层单词标签关联读写：执行删除、批量插入，事务及替换顺序由 Service 管理。"""

from __future__ import annotations

import psycopg

from thoth.entity import WordTagEntity


class WordTagTblMapper:
    """封装 word_tag_tbl SQL，不提交事务，不决定替换策略。"""

    def __init__(self, connection: psycopg.Connection) -> None:
        """绑定 Service 的连接，使关联写入与单词写入共用事务。"""
        self._connection = connection

    def delete_by_word_id(self, word_id: int) -> None:
        """删除该单词全部关联；零行删除也正常返回，驱动异常交由 Service 处理。"""
        # 仅删除指定单词的所有关联，不删除标签字典或其他单词的关联。
        sql = "DELETE FROM word_tag_tbl WHERE word_id = %(word_id)s"
        with self._connection.cursor() as cursor:
            cursor.execute(sql, {"word_id": word_id})

    def insert_many(self, entities: list[WordTagEntity]) -> None:
        """在当前事务内批量插入关联实体，空集合不执行 SQL，任何失败均向上传递。"""
        if not entities:
            return
        # 审计账号使用 CURRENT_USER，时间使用数据库默认值；不忽略主键或外键冲突，以便 Service 回滚整个单词。
        sql = """
        INSERT INTO word_tag_tbl (word_id, tag_code, created_by, updated_by)
        VALUES (%(word_id)s, %(tag_code)s, CURRENT_USER, CURRENT_USER)
        """
        with self._connection.cursor() as cursor:
            cursor.executemany(sql, [
                {"word_id": entity.word_id, "tag_code": entity.tag_code}
                for entity in entities
            ])
