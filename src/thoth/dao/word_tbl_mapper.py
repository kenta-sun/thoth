"""DAO 层的单词表 SQL 映射：查询及写入返回实体，事务和业务判断由 Service 管理。"""

from __future__ import annotations

import psycopg
from psycopg.rows import class_row

from thoth.entity import WordEntity


class WordTblMapper:
    """封装 word_tbl 的参数化 SQL 调用，不提交事务或判断业务操作。"""

    def __init__(self, connection: psycopg.Connection, *, operator: str = "THOTH_MCP") -> None:
        """复用 Service 的连接，使用 operator 填充写入审计字段。"""
        self._connection = connection
        self._operator = operator

    def find_existing_words(self, words: list[str]) -> list[WordEntity]:
        """按原文查询包含已删除状态的单词；空列表不查询，不加锁，驱动异常向上传递。"""
        if not words:
            return []
        # 按 word 原文一次查询本批已有记录，包含已标记删除的词；不加行锁，
        # 因此结果只反映查询时的存在性，保存时仍需处理并发新增或外部删除。
        sql = """
        SELECT id, word, common_form, hiragana, meaning, status_code,
               created_at, updated_at, created_by, updated_by
        FROM word_tbl
        WHERE word = ANY(%(words)s)
        """
        with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
            cursor.execute(sql, {"words": words})
            return cursor.fetchall()

    def insert(self, entity: WordEntity) -> WordEntity | None:
        """在调用方事务内新增；返回数据库生成的实体，唯一键冲突时返回 None。"""
        # 仅写业务字段和操作者，id、状态和时间交给数据库默认值生成。
        # word 的唯一约束配合 ON CONFLICT 避免并发新增时覆盖原记录；
        # RETURNING 返回实际新增的完整行，发生冲突而未写入时不返回记录。
        sql = """
        INSERT INTO word_tbl (word, common_form, hiragana, meaning, created_by, updated_by)
        VALUES (%(word)s, %(common_form)s, %(hiragana)s, %(meaning)s, %(operator)s, %(operator)s)
        ON CONFLICT (word) DO NOTHING
        RETURNING id, word, common_form, hiragana, meaning, status_code,
                  created_at, updated_at, created_by, updated_by
        """
        with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
            cursor.execute(sql, self._parameters(entity))
            return cursor.fetchone()

    def update(self, entity: WordEntity) -> WordEntity | None:
        """按 word 更新并锁行；None 信息字段保留原值，零行更新返回 None，由 Service 判断。"""
        # 只按 word 定位并更新三个信息字段及修改审计字段，不修改 word 或状态。
        # COALESCE 把请求中的 None 视为“保留当前数据库值”，避免清空原值，
        # 也避免使用批量查询时的旧实体覆盖其他请求刚修改的字段。
        # UPDATE 由数据库取得行锁；RETURNING 用于取得实际结果并识别零行更新。
        sql = """
        UPDATE word_tbl
        SET common_form = COALESCE(%(common_form)s, common_form),
            hiragana = COALESCE(%(hiragana)s, hiragana),
            meaning = COALESCE(%(meaning)s, meaning),
            updated_at = CURRENT_TIMESTAMP,
            updated_by = %(operator)s
        WHERE word = %(word)s
        RETURNING id, word, common_form, hiragana, meaning, status_code,
                  created_at, updated_at, created_by, updated_by
        """
        with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
            cursor.execute(sql, self._parameters(entity))
            return cursor.fetchone()

    def _parameters(self, entity: WordEntity) -> dict[str, str | None]:
        """在 SQL 绑定处读取业务字段和操作者，保留 None，不绑定 ID、状态及时间。"""
        return {
            "word": entity.word,
            "operator": self._operator,
            "common_form": entity.common_form,
            "hiragana": entity.hiragana,
            "meaning": entity.meaning,
        }
