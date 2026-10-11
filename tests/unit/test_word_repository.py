"""覆盖实体行映射、局部更新、冲突处理与单项失败恢复。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.pq import ExecStatus

from thoth.dao.word_tbl_mapper import WordTblMapper
from thoth.entity import WordEntity

CREATED_AT = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
UPDATED_AT = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
WORD_COLUMNS = (
    "id", "word", "common_form", "hiragana", "meaning", "status_code",
    "created_at", "updated_at", "created_by", "updated_by",
)


def database_row(
    word: str = "食べる", *, record_id: int = 7, meaning: str = "吃",
    status_code: str = "A", created_by: str | None = "THOTH_MCP",
    updated_by: str | None = "THOTH_MCP",
) -> tuple[object, ...]:
    """模拟驱动已经完成 PostgreSQL 类型适配的原始行。"""
    return (
        record_id, word, word, "たべる", meaning, status_code,
        CREATED_AT, UPDATED_AT, created_by, updated_by,
    )


def result_columns(query: str) -> tuple[str, ...]:
    """从固定 SQL 的结果列构造驱动元数据，避免创建实体绕过 class_row。"""
    before, returning, after = query.partition("RETURNING")
    selected = after if returning else before.partition("SELECT")[2].partition("FROM")[0]
    return tuple(column.strip() for column in selected.split(","))


class ScriptedConnection:
    """执行真实 row factory，并记录固定 SQL、提交及回滚边界。"""

    def __init__(
        self, *responses: tuple[object, ...] | list[tuple[object, ...]] | None | Exception
    ) -> None:
        self.responses = iter(responses)
        self.statements: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0
        self.last_response: tuple[object, ...] | list[tuple[object, ...]] | None = None
        self._encoding = "utf-8"

    @contextmanager
    def transaction(self):
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    @contextmanager
    def cursor(self, *, row_factory=None):
        self.row_factory = row_factory
        yield self

    def execute(self, query: str, params: dict) -> None:
        self.statements.append((query, params.copy()))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        self.last_response = response
        columns = result_columns(query)
        self.pgresult = SimpleNamespace(
            status=ExecStatus.TUPLES_OK,
            nfields=len(columns),
            fname=lambda index: columns[index].encode(self._encoding),
        )
        self.make_row = self.row_factory(self) if self.row_factory else None

    def executemany(self, query, params_list):
        """逐条消费模拟响应，用于验证批量插入参数及中途失败。"""
        for params in params_list:
            self.execute(query, params)

    def fetchone(self) -> WordEntity | None:
        assert not isinstance(self.last_response, list)
        return None if self.last_response is None else self.make_row(self.last_response)

    def fetchall(self) -> list[WordEntity]:
        assert isinstance(self.last_response, list)
        return [self.make_row(row) for row in self.last_response]


@pytest.fixture
def complete_entity() -> WordEntity:
    return WordEntity(word="食べる", common_form="食べる", hiragana="たべる", meaning="吃")


def test_find_existing_words_uses_one_parameterized_query_and_returns_entities():
    words = ["食べる", "飲む", "読む'; DROP TABLE word_tbl; --"]
    connection = ScriptedConnection([
        database_row("食べる"), database_row("飲む", record_id=8, status_code="D"),
    ])

    entities = WordTblMapper(connection).find_existing_words(words)

    assert all(isinstance(entity, WordEntity) for entity in entities)
    assert [entity.word for entity in entities] == ["食べる", "飲む"]
    assert entities[1].status_code == "D"
    assert len(connection.statements) == 1
    query, params = connection.statements[0]
    assert result_columns(query) == WORD_COLUMNS
    assert query.split("WHERE", 1)[1].strip() == "word = ANY(%(words)s)"
    assert "FOR UPDATE" not in query
    assert params == {"words": words}
    assert all(word not in query for word in words)


def test_find_existing_words_with_empty_input_does_not_query():
    connection = ScriptedConnection()

    assert WordTblMapper(connection).find_existing_words([]) == []
    assert connection.statements == []


def test_absent_word_is_created_with_all_fields_and_database_generated_values(complete_entity):
    connection = ScriptedConnection(database_row(created_by="test-operator", updated_by="test-operator"))
    result = WordTblMapper(connection, operator="test-operator").insert(complete_entity)

    assert isinstance(result, WordEntity)
    assert result is not complete_entity
    assert result.id == 7
    assert result.status_code == "A"
    assert result.created_at == CREATED_AT
    assert result.updated_at == UPDATED_AT
    assert result.created_by == result.updated_by == "test-operator"
    query, params = connection.statements[-1]
    assert "INSERT INTO word_tbl" in query
    assert "ON CONFLICT (word) DO NOTHING" in query
    assert params == {
        "word": "食べる", "operator": "test-operator",
        "common_form": "食べる", "hiragana": "たべる", "meaning": "吃",
    }
    assert query.split("VALUES", 1)[0].strip() == (
        "INSERT INTO word_tbl (word, common_form, hiragana, meaning, created_by, updated_by)"
    )
    assert result_columns(query) == WORD_COLUMNS
    assert complete_entity.id is complete_entity.status_code is complete_entity.created_at is None
    assert connection.commits == 0
    assert connection.rollbacks == 0


def test_existing_update_only_changes_supplied_fields_and_returns_database_entity():
    connection = ScriptedConnection(database_row(meaning="吃；食用", status_code="D"))
    result = WordTblMapper(connection).update(WordEntity(word="食べる", meaning="吃；食用"))

    assert result == WordEntity(
        id=7, word="食べる", common_form="食べる", hiragana="たべる", meaning="吃；食用",
        status_code="D", created_at=CREATED_AT, updated_at=UPDATED_AT,
        created_by="THOTH_MCP", updated_by="THOTH_MCP",
    )
    query, params = connection.statements[-1]
    assert params["common_form"] is None
    assert params["hiragana"] is None
    assert params["meaning"] == "吃；食用"
    assert "COALESCE(%(common_form)s, common_form)" in query
    assert "COALESCE(%(hiragana)s, hiragana)" in query
    assert "updated_at = CURRENT_TIMESTAMP" in query
    assert "updated_by = %(operator)s" in query
    assert "status_code" not in query.split("RETURNING", 1)[0]
    assert result_columns(query) == WORD_COLUMNS


def test_sql_values_are_bound_and_exact_word_is_preserved(complete_entity):
    word = "  食べる'; DROP TABLE word_tbl; --  "
    connection = ScriptedConnection(database_row(word))
    WordTblMapper(connection).insert(replace(complete_entity, word=word))

    for query, params in connection.statements:
        assert word not in query
        assert params["word"] == word



@pytest.mark.parametrize("method", ["insert", "update"])
def test_zero_returning_rows_and_driver_errors_are_left_to_service(method, complete_entity):
    connection = ScriptedConnection(None, psycopg.errors.CheckViolation("driver detail"))
    mapper = WordTblMapper(connection)
    assert getattr(mapper, method)(complete_entity) is None
    with pytest.raises(psycopg.errors.CheckViolation):
        getattr(mapper, method)(complete_entity)
    assert connection.commits == connection.rollbacks == 0


def test_query_driver_errors_propagate_to_service():
    connection = ScriptedConnection(psycopg.errors.UndefinedTable("driver detail"))
    with pytest.raises(psycopg.errors.UndefinedTable):
        WordTblMapper(connection).find_existing_words(["食べる"])
