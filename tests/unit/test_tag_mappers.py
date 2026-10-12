"""用脚本化驱动验证标签 SQL、实体映射和真实 Service/Mapper 调用链，不连接数据库。"""

import json

import psycopg
import pytest

from thoth.dao.tag_tbl_mapper import TagTblMapper
from thoth.dao.word_tag_tbl_mapper import WordTagTblMapper
from thoth.entity import TagEntity, WordTagEntity
from thoth.service.add_update_words_service import parse_words_text, save_word_batch, serialize_word_batch
from tests.unit.test_word_repository import ScriptedConnection, database_row, CREATED_AT, UPDATED_AT


def tag_row(code="v"):
    """按标签 SQL 列顺序模拟驱动返回的完整记录。"""
    return (code, "动词", "動詞", CREATED_AT, UPDATED_AT, "operator", "operator")


def test_tag_query_maps_entities_and_binds_codes_without_transactions():
    connection = ScriptedConnection([tag_row()])
    codes = ["v", "unknown"]
    rows = TagTblMapper(connection).find_by_codes(codes)
    assert rows == [TagEntity(code="v", zh_name="动词", jp_name="動詞",
                              created_at=CREATED_AT, updated_at=UPDATED_AT,
                              created_by="operator", updated_by="operator")]
    query, params = connection.statements[0]
    assert "WHERE code = ANY(%(codes)s)" in query
    assert params == {"codes": codes}
    assert connection.commits == connection.rollbacks == 0


def test_empty_mapper_collections_do_not_execute_sql():
    connection = ScriptedConnection()
    assert TagTblMapper(connection).find_by_codes([]) == []
    WordTagTblMapper(connection).insert_many([])
    assert connection.statements == []


def test_association_delete_and_insert_are_scoped_and_parameterized():
    connection = ScriptedConnection(None, None, None)
    mapper = WordTagTblMapper(connection)
    mapper.delete_by_word_id(9)
    mapper.insert_many([
        WordTagEntity(word_id=9, tag_code=code, created_by="tester", updated_by="tester")
        for code in ["v", "v2"]
    ])
    assert connection.statements[0] == (
        "DELETE FROM word_tag_tbl WHERE word_id = %(word_id)s", {"word_id": 9}
    )
    for (query, params), code in zip(connection.statements[1:], ["v", "v2"], strict=True):
        assert "ON CONFLICT" not in query
        assert params == {"word_id": 9, "tag_code": code, "created_by": "tester", "updated_by": "tester"}
    assert connection.commits == connection.rollbacks == 0


def test_mapper_does_not_swallow_partial_insert_errors():
    connection = ScriptedConnection(None, psycopg.errors.ForeignKeyViolation("internal"))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        WordTagTblMapper(connection).insert_many([
            WordTagEntity(word_id=7, tag_code="v"), WordTagEntity(word_id=7, tag_code="v2")
        ])
    assert len(connection.statements) == 2
    assert connection.commits == connection.rollbacks == 0


def test_json_through_all_mappers_preserves_update_and_replaces_tags():
    connection = ScriptedConnection(
        [database_row("飲む", meaning="旧释义", status_code="D")],
        [tag_row("v"), tag_row("v2")], database_row("食べる", record_id=8), None, None, None,
        [tag_row("v")], database_row("飲む", meaning="喝", status_code="D"), None, None,
    )
    requests = parse_words_text(json.dumps([
        {"word": "食べる", "common_form": "食べる", "hiragana": "たべる", "meaning": "吃", "tags": ["v", "v2"]},
        {"word": "飲む", "meaning": "喝", "tags": ["v"], "operation": {"action": "update"}},
    ]))
    result = serialize_word_batch(save_word_batch(requests, connection))
    assert result == {"results": [
        {"index": 0, "word": "食べる", "status": "created"},
        {"index": 1, "word": "飲む", "status": "updated"},
    ]}
    assert connection.commits == 2 and connection.rollbacks == 0
    assert [query.split()[0] for query, _ in connection.statements] == [
        "SELECT", "SELECT", "INSERT", "DELETE", "INSERT", "INSERT",
        "SELECT", "UPDATE", "DELETE", "INSERT",
    ]
    assert connection.statements[3][1] == {"word_id": 8}
    assert connection.statements[8][1] == {"word_id": 7}
    assert connection.statements[7][1] == {
        "word": "飲む", "common_form": None, "hiragana": None,
        "meaning": "喝", "operator": "THOTH_MCP",
    }


def test_real_mapper_error_rolls_back_before_next_word_transaction():
    connection = ScriptedConnection(
        [], [tag_row()], database_row(), None,
        psycopg.errors.ForeignKeyViolation("secret driver detail"),
        [tag_row()], database_row("飲む", record_id=8), None, None,
    )
    requests = parse_words_text(json.dumps([
        {"word": word, "common_form": word, "hiragana": "かな", "meaning": "释义", "tags": ["v"]}
        for word in ["食べる", "飲む"]
    ]))
    results = save_word_batch(requests, connection).results
    assert [row.status for row in results] == ["failed", "created"]
    assert "23503" in results[0].reason and "secret" not in results[0].reason
    assert connection.rollbacks == connection.commits == 1
