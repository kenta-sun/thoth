"""单词表的固定 SQL 操作；每次保存独立完成，失败不会影响下一次保存。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import psycopg

from thoth.db.connection import DatabaseError

_INFORMATION_FIELDS = ("common_form", "hiragana", "meaning")

_SQL_FIND_EXISTING_WORDS = """
SELECT word
FROM word_tbl
WHERE word = ANY(%(words)s)
"""

_SQL_INSERT_WORD = """
INSERT INTO word_tbl (word, common_form, hiragana, meaning, created_by, updated_by)
VALUES (%(word)s, %(common_form)s, %(hiragana)s, %(meaning)s, %(operator)s, %(operator)s)
ON CONFLICT (word) DO NOTHING
RETURNING id
"""

_SQL_UPDATE_WORD = """
UPDATE word_tbl
SET common_form = COALESCE(%(common_form)s, common_form),
    hiragana = COALESCE(%(hiragana)s, hiragana),
    meaning = COALESCE(%(meaning)s, meaning),
    updated_at = CURRENT_TIMESTAMP,
    updated_by = %(operator)s
WHERE word = %(word)s
RETURNING id
"""


@dataclass(frozen=True, slots=True)
class SaveResult:
    status: Literal["created", "updated", "skipped"]
    reason: str | None = None


class MissingWordFieldsError(ValueError):
    """实际需要新增时，报告尚未提供有效值的信息字段。"""

    def __init__(self, fields: tuple[str, ...]) -> None:
        self.fields = fields
        super().__init__(f"需要新增单词，但以下字段缺失或为空：{', '.join(fields)}。")


class WordRepository:
    """绑定一条 autocommit=True 的连接，其生命周期由调用方管理。"""

    def __init__(
        self, connection: psycopg.Connection, *, operator: str = "THOTH_MCP"
    ) -> None:
        self._connection = connection
        self._operator = operator

    def find_existing_words(self, words: list[str]) -> set[str]:
        """一次查出本批次已存在的词，包含已标记删除的记录。"""
        if not words:
            return set()
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(_SQL_FIND_EXISTING_WORDS, {"words": words})
                return {row[0] for row in cursor.fetchall()}
        except psycopg.Error as exc:
            code = f"（SQLSTATE {exc.sqlstate}）" if exc.sqlstate else ""
            raise DatabaseError(f"查询已有单词失败{code}，请稍后重试。") from exc

    def save(
        self,
        *,
        word: str,
        action: Literal["create", "update"],
        values: dict[str, str | None],
        exists: bool,
    ) -> SaveResult:
        """根据批量查询结果保存一项；values 中空值已由业务层归一为 None。"""
        if action not in ("create", "update"):
            raise ValueError("action 仅允许 create 或 update。")

        params = self._parameters(word, values)
        if exists:
            if action == "create":
                return SaveResult("skipped", "单词已存在，未覆盖已有信息。")
            if all(params[field] is None for field in _INFORMATION_FIELDS):
                return SaveResult("skipped", "未提供需要修改的有效字段。")
        else:
            self._require_new_word_fields(params)

        try:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    if exists:
                        return self._update(cursor, params)

                    if self._insert(cursor, params):
                        return SaveResult("created")

                    # 唯一约束处理查询后发生的并发新增。create 不覆盖；
                    # update 用固定 UPDATE 合并本项字段，并由数据库取得行锁。
                    if action == "create":
                        return SaveResult("skipped", "单词已存在，未覆盖已有信息。")
                    return self._update(cursor, params)
        except psycopg.Error as exc:
            # transaction 上下文已经回滚，不向调用方暴露 SQL、参数或连接信息。
            code = f"（SQLSTATE {exc.sqlstate}）" if exc.sqlstate else ""
            raise DatabaseError(f"保存单词失败{code}，请稍后重试。") from exc

    def _parameters(
        self, word: str, values: dict[str, str | None]
    ) -> dict[str, str | None]:
        return {
            "word": word,
            "operator": self._operator,
            **{field: values.get(field) for field in _INFORMATION_FIELDS},
        }

    @staticmethod
    def _require_new_word_fields(params: dict[str, str | None]) -> None:
        missing = tuple(
            field for field in _INFORMATION_FIELDS if params[field] is None
        )
        if missing:
            raise MissingWordFieldsError(missing)

    @staticmethod
    def _insert(cursor: psycopg.Cursor, params: dict[str, str | None]) -> bool:
        cursor.execute(_SQL_INSERT_WORD, params)
        return cursor.fetchone() is not None

    @staticmethod
    def _update(
        cursor: psycopg.Cursor,
        params: dict[str, str | None],
    ) -> SaveResult:
        cursor.execute(_SQL_UPDATE_WORD, params)
        if cursor.fetchone() is None:
            # 当前工具不物理删除行。若外部操作在批量查询或新增冲突后删除了该行，
            # 明确报告失败，避免将零行更新误报为成功。
            raise DatabaseError("保存期间单词记录发生变化，请重试。")
        return SaveResult("updated")
