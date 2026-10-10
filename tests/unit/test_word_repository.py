"""覆盖实体行映射、局部更新、冲突处理与单项失败恢复。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.pq import ExecStatus

from thoth.db import word_repo
from thoth.db.connection import DatabaseError
from thoth.db.word_repo import MissingWordFieldsError, WordRepository
from thoth.entities import WordEntity
from thoth.word_service import parse_words_text, save_word_batch, serialize_word_batch

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
    def cursor(self, *, row_factory):
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
        self.make_row = self.row_factory(self)

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

    entities = WordRepository(connection).find_existing_words(words)

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


def test_class_row_maps_reordered_column_names_and_preserves_nullable_audit_fields(monkeypatch):
    columns = tuple(reversed(WORD_COLUMNS))
    monkeypatch.setattr(
        word_repo, "_SQL_FIND_EXISTING_WORDS",
        f"SELECT {', '.join(columns)} FROM word_tbl WHERE word = ANY(%(words)s)",
    )
    row = database_row(status_code="D", created_by=None, updated_by=None)
    connection = ScriptedConnection([tuple(reversed(row))])

    entity, = WordRepository(connection).find_existing_words(["食べる"])

    assert entity == WordEntity(
        id=7, word="食べる", common_form="食べる", hiragana="たべる", meaning="吃",
        status_code="D", created_at=CREATED_AT, updated_at=UPDATED_AT,
        created_by=None, updated_by=None,
    )
    assert entity.created_at.tzinfo is timezone.utc
    assert entity.updated_at.tzinfo is timezone.utc


def test_find_existing_words_with_empty_input_does_not_query():
    connection = ScriptedConnection()

    assert WordRepository(connection).find_existing_words([]) == []
    assert connection.statements == []


def test_find_existing_words_sanitizes_database_errors():
    connection = ScriptedConnection(
        psycopg.errors.UndefinedTable("secret driver message and SQL")
    )
    with pytest.raises(DatabaseError) as exc_info:
        WordRepository(connection).find_existing_words(["食べる"])

    assert "secret" not in str(exc_info.value)
    assert "42P01" in str(exc_info.value)


def test_one_batch_query_followed_by_100_saves_has_no_extra_selects(complete_entity):
    words = [f"word-{index}" for index in range(100)]
    connection = ScriptedConnection(
        [database_row(word) for word in words[::2]],
        *(database_row(word, record_id=index) for index, word in enumerate(words)),
    )
    repository = WordRepository(connection)
    existing_words = {entity.word for entity in repository.find_existing_words(words)}

    for word in words:
        result = repository.save(
            replace(complete_entity, word=word), action="update", exists=word in existing_words,
        )
        assert result.status == ("updated" if word in existing_words else "created")
        assert result.entity.word == word

    assert sum(query.lstrip().startswith("SELECT") for query, _ in connection.statements) == 1
    assert len(connection.statements) == 101
    assert connection.commits == 100


@pytest.mark.parametrize("action", ["create", "update"])
def test_absent_word_is_created_with_all_fields_and_database_generated_values(action, complete_entity):
    connection = ScriptedConnection(database_row(created_by="test-operator", updated_by="test-operator"))
    result = WordRepository(connection, operator="test-operator").save(
        complete_entity, action=action, exists=False,
    )

    assert result.status == "created"
    assert isinstance(result.entity, WordEntity)
    assert result.entity is not complete_entity
    assert result.entity.id == 7
    assert result.entity.status_code == "A"
    assert result.entity.created_at == CREATED_AT
    assert result.entity.updated_at == UPDATED_AT
    assert result.entity.created_by == result.entity.updated_by == "test-operator"
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
    assert connection.commits == 1
    assert connection.rollbacks == 0


@pytest.mark.parametrize("meaning", [None, "覆盖值"])
def test_existing_create_skips_without_requiring_or_overwriting_fields(meaning):
    connection = ScriptedConnection()
    result = WordRepository(connection).save(
        WordEntity(word="食べる", meaning=meaning), action="create", exists=True,
    )

    assert result.status == "skipped"
    assert result.entity is None
    assert connection.statements == []
    assert connection.commits == 0


def test_existing_update_only_changes_supplied_fields_and_returns_database_entity():
    connection = ScriptedConnection(database_row(meaning="吃；食用", status_code="D"))
    result = WordRepository(connection).save(
        WordEntity(word="食べる", meaning="吃；食用"), action="update", exists=True,
    )

    assert result.status == "updated"
    assert result.entity == WordEntity(
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


def test_existing_update_with_no_effective_fields_skips():
    connection = ScriptedConnection()
    result = WordRepository(connection).save(
        WordEntity(word="食べる"), action="update", exists=True,
    )

    assert result.status == "skipped"
    assert connection.statements == []
    assert connection.commits == 0


@pytest.mark.parametrize("action", ["create", "update"])
def test_missing_creation_fields_are_reported_only_for_absent_words(action):
    connection = ScriptedConnection()
    with pytest.raises(MissingWordFieldsError) as exc_info:
        WordRepository(connection).save(
            WordEntity(word="食べる", meaning="吃"), action=action, exists=False,
        )

    assert exc_info.value.fields == ("common_form", "hiragana")
    assert "common_form" in str(exc_info.value)
    assert "hiragana" in str(exc_info.value)
    assert connection.statements == []
    assert connection.rollbacks == 0
    assert connection.commits == 0


def test_concurrent_insert_conflict_in_create_skips_without_update(complete_entity):
    connection = ScriptedConnection(None)
    result = WordRepository(connection).save(complete_entity, action="create", exists=False)

    assert result.status == "skipped"
    assert result.entity is None
    assert len(connection.statements) == 1
    assert connection.commits == 1


def test_concurrent_insert_conflict_in_update_updates_the_existing_row(complete_entity):
    connection = ScriptedConnection(None, database_row())
    result = WordRepository(connection).save(complete_entity, action="update", exists=False)

    assert result.status == "updated"
    assert result.entity.id == 7
    assert "UPDATE word_tbl" in connection.statements[-1][0]
    assert connection.commits == 1


def test_external_deletion_after_insert_conflict_is_not_reported_as_success(complete_entity):
    connection = ScriptedConnection(None, None)
    with pytest.raises(DatabaseError, match="记录发生变化"):
        WordRepository(connection).save(complete_entity, action="update", exists=False)

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_external_deletion_after_batch_query_is_not_reported_as_success():
    connection = ScriptedConnection(None)
    with pytest.raises(DatabaseError, match="记录发生变化"):
        WordRepository(connection).save(
            WordEntity(word="食べる", meaning="吃"), action="update", exists=True,
        )

    assert len(connection.statements) == 1
    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_failed_save_rolls_back_and_next_save_can_succeed(complete_entity):
    connection = ScriptedConnection(
        psycopg.errors.CheckViolation("secret driver message and SQL"),
        database_row("飲む", record_id=8),
    )
    repository = WordRepository(connection)
    with pytest.raises(DatabaseError) as exc_info:
        repository.save(complete_entity, action="create", exists=False)

    assert "secret" not in str(exc_info.value)
    assert "23514" in str(exc_info.value)
    result = repository.save(
        replace(complete_entity, word="飲む"), action="create", exists=False,
    )
    assert result.status == "created"
    assert result.entity.word == "飲む"
    assert connection.rollbacks == 1
    assert connection.commits == 1


def test_sql_values_are_bound_and_exact_word_is_preserved(complete_entity):
    word = "  食べる'; DROP TABLE word_tbl; --  "
    connection = ScriptedConnection(database_row(word))
    WordRepository(connection).save(
        replace(complete_entity, word=word), action="create", exists=False,
    )

    for query, params in connection.statements:
        assert word not in query
        assert params["word"] == word


def test_unknown_action_cannot_trigger_a_write():
    connection = ScriptedConnection()
    with pytest.raises(ValueError, match="action"):
        WordRepository(connection).save(WordEntity(word="食べる"), action="delete", exists=False)

    assert connection.statements == []


def test_json_to_repository_entity_round_trip_preserves_partial_update_and_output():
    connection = ScriptedConnection(
        [database_row("飲む", meaning="旧释义", status_code="D")],
        database_row("食べる"),
        database_row("飲む", meaning="喝", status_code="D"),
    )
    requests = parse_words_text('''[
        {"word":"食べる", "common_form":"食べる", "hiragana":"たべる", "meaning":"吃"},
        {"word":"飲む", "meaning":"喝", "operation":{"action":"update"}}
    ]''')

    result = serialize_word_batch(save_word_batch(requests, WordRepository(connection)))

    assert result == {"results": [
        {"index": 0, "word": "食べる", "status": "created"},
        {"index": 1, "word": "飲む", "status": "updated"},
    ]}
    assert sum(query.lstrip().startswith("SELECT") for query, _ in connection.statements) == 1
    assert len(connection.statements) == 3
    assert connection.statements[0][1] == {"words": ["食べる", "飲む"]}
    query, params = connection.statements[-1]
    assert query.lstrip().startswith("UPDATE")
    assert params == {
        "word": "飲む", "common_form": None, "hiragana": None,
        "meaning": "喝", "operator": "THOTH_MCP",
    }
    assert requests[1].entity.common_form is requests[1].entity.hiragana is None
    assert connection.commits == 2
    assert connection.rollbacks == 0
