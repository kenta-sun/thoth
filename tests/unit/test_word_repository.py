"""覆盖单词仓储的创建、局部更新、冲突处理与单项失败恢复。"""

from __future__ import annotations

from contextlib import contextmanager

import psycopg
import pytest

from thoth.db.connection import DatabaseError
from thoth.db.word_repo import MissingWordFieldsError, WordRepository


class ScriptedConnection:
    """按预定数据库结果驱动仓储，并记录提交与回滚边界。"""

    def __init__(
        self, *responses: tuple[int] | list[tuple[str]] | None | Exception
    ) -> None:
        self.responses = iter(responses)
        self.statements: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0
        self.last_response: tuple[int] | list[tuple[str]] | None = None

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
    def cursor(self):
        yield self

    def execute(self, query: str, params: dict) -> None:
        self.statements.append((query, params.copy()))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        self.last_response = response

    def fetchone(self) -> tuple[int] | None:
        assert not isinstance(self.last_response, list)
        return self.last_response

    def fetchall(self) -> list[tuple[str]]:
        assert isinstance(self.last_response, list)
        return self.last_response


@pytest.fixture
def complete_values() -> dict[str, str]:
    return {"common_form": "食べる", "hiragana": "たべる", "meaning": "吃"}


def test_find_existing_words_uses_one_parameterized_query():
    words = ["食べる", "飲む", "読む'; DROP TABLE word_tbl; --"]
    connection = ScriptedConnection([("食べる",), ("飲む",)])

    assert WordRepository(connection).find_existing_words(words) == {"食べる", "飲む"}
    assert len(connection.statements) == 1
    query, params = connection.statements[0]
    assert "SELECT word" in query
    assert "WHERE word = ANY(%(words)s)" in query
    assert "FOR UPDATE" not in query
    assert "status_code" not in query
    assert params == {"words": words}
    assert all(word not in query for word in words)


def test_find_existing_words_with_empty_input_does_not_query():
    connection = ScriptedConnection()

    assert WordRepository(connection).find_existing_words([]) == set()
    assert connection.statements == []


def test_find_existing_words_sanitizes_database_errors():
    connection = ScriptedConnection(
        psycopg.errors.UndefinedTable("secret driver message and SQL")
    )
    with pytest.raises(DatabaseError) as exc_info:
        WordRepository(connection).find_existing_words(["食べる"])

    assert "secret" not in str(exc_info.value)
    assert "42P01" in str(exc_info.value)


def test_one_batch_query_followed_by_100_saves_has_no_extra_selects(complete_values):
    words = [f"word-{index}" for index in range(100)]
    connection = ScriptedConnection(
        [(word,) for word in words[::2]], *[(index,) for index in range(100)]
    )
    repository = WordRepository(connection)
    existing_words = repository.find_existing_words(words)

    for word in words:
        result = repository.save(
            word=word,
            action="update",
            values=complete_values,
            exists=word in existing_words,
        )
        assert result.status == ("updated" if word in existing_words else "created")

    assert sum(query.lstrip().startswith("SELECT") for query, _ in connection.statements) == 1
    assert len(connection.statements) == 101
    assert connection.commits == 100


@pytest.mark.parametrize("action", ["create", "update"])
def test_absent_word_is_created_with_all_fields(action, complete_values):
    connection = ScriptedConnection((7,))
    result = WordRepository(connection, operator="test-operator").save(
        word="食べる", action=action, values=complete_values, exists=False
    )

    assert result.status == "created"
    query, params = connection.statements[-1]
    assert "INSERT INTO word_tbl" in query
    assert "ON CONFLICT (word) DO NOTHING" in query
    assert params == {"word": "食べる", "operator": "test-operator", **complete_values}
    assert "status_code" not in query
    assert connection.commits == 1
    assert connection.rollbacks == 0


@pytest.mark.parametrize("values", [{}, {"meaning": "覆盖值"}, {"meaning": None}])
def test_existing_create_skips_without_requiring_or_overwriting_fields(values):
    connection = ScriptedConnection()
    result = WordRepository(connection).save(
        word="食べる", action="create", values=values, exists=True
    )

    assert result.status == "skipped"
    assert connection.statements == []
    assert connection.commits == 0


def test_existing_update_only_changes_supplied_fields():
    connection = ScriptedConnection((7,))
    result = WordRepository(connection).save(
        word="食べる", action="update", values={"meaning": "吃；食用"}, exists=True
    )

    assert result.status == "updated"
    query, params = connection.statements[-1]
    assert params["common_form"] is None
    assert params["hiragana"] is None
    assert params["meaning"] == "吃；食用"
    assert "COALESCE(%(common_form)s, common_form)" in query
    assert "COALESCE(%(hiragana)s, hiragana)" in query
    assert "updated_at = CURRENT_TIMESTAMP" in query
    assert "updated_by = %(operator)s" in query
    assert "status_code" not in query


def test_existing_update_with_no_effective_fields_skips():
    connection = ScriptedConnection()
    result = WordRepository(connection).save(
        word="食べる", action="update", values={"meaning": None}, exists=True
    )

    assert result.status == "skipped"
    assert connection.statements == []
    assert connection.commits == 0


@pytest.mark.parametrize("action", ["create", "update"])
def test_missing_creation_fields_are_reported_only_for_absent_words(action):
    connection = ScriptedConnection()
    with pytest.raises(MissingWordFieldsError) as exc_info:
        WordRepository(connection).save(
            word="食べる", action=action, values={"meaning": "吃"}, exists=False
        )

    assert exc_info.value.fields == ("common_form", "hiragana")
    assert "common_form" in str(exc_info.value)
    assert "hiragana" in str(exc_info.value)
    assert connection.statements == []
    assert connection.rollbacks == 0
    assert connection.commits == 0


def test_concurrent_insert_conflict_in_create_skips_without_update(complete_values):
    connection = ScriptedConnection(None)
    result = WordRepository(connection).save(
        word="食べる", action="create", values=complete_values, exists=False
    )

    assert result.status == "skipped"
    assert len(connection.statements) == 1
    assert connection.commits == 1


def test_concurrent_insert_conflict_in_update_updates_the_existing_row(complete_values):
    connection = ScriptedConnection(None, (7,))
    result = WordRepository(connection).save(
        word="食べる", action="update", values=complete_values, exists=False
    )

    assert result.status == "updated"
    assert "UPDATE word_tbl" in connection.statements[-1][0]
    assert connection.commits == 1


def test_external_deletion_after_insert_conflict_is_not_reported_as_success(complete_values):
    connection = ScriptedConnection(None, None)
    with pytest.raises(DatabaseError, match="记录发生变化"):
        WordRepository(connection).save(
            word="食べる", action="update", values=complete_values, exists=False
        )

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_external_deletion_after_batch_query_is_not_reported_as_success():
    connection = ScriptedConnection(None)
    with pytest.raises(DatabaseError, match="记录发生变化"):
        WordRepository(connection).save(
            word="食べる", action="update", values={"meaning": "吃"}, exists=True
        )

    assert len(connection.statements) == 1
    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_failed_save_rolls_back_and_next_save_can_succeed(complete_values):
    connection = ScriptedConnection(
        psycopg.errors.CheckViolation("secret driver message and SQL"),
        (8,),
    )
    repository = WordRepository(connection)
    with pytest.raises(DatabaseError) as exc_info:
        repository.save(
            word="食べる", action="create", values=complete_values, exists=False
        )

    assert "secret" not in str(exc_info.value)
    assert "23514" in str(exc_info.value)
    result = repository.save(
        word="飲む", action="create", values=complete_values, exists=False
    )
    assert result.status == "created"
    assert connection.rollbacks == 1
    assert connection.commits == 1


def test_sql_values_are_bound_and_exact_word_is_preserved(complete_values):
    word = "  食べる'; DROP TABLE word_tbl; --  "
    connection = ScriptedConnection((7,))
    WordRepository(connection).save(
        word=word, action="create", values=complete_values, exists=False
    )

    for query, params in connection.statements:
        assert word not in query
        assert params["word"] == word


def test_unknown_action_cannot_trigger_a_write():
    connection = ScriptedConnection()
    with pytest.raises(ValueError, match="action"):
        WordRepository(connection).save(
            word="食べる", action="delete", values={}, exists=False
        )

    assert connection.statements == []
