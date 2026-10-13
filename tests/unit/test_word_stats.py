"""验证批量计数的过滤、用户查询及三条统计 SQL、失败边界及原清零协议。"""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from fastmcp import Client
from thoth.db.connection import DatabaseError

from thoth.service import count_word_usage_service as usage_service
from thoth.service import count_word_miss_service as miss_service
from thoth.service import reset_word_miss_service as reset_service
from thoth.service.word_stats_input_service import prepare_word_list, merge_stats_results
from thoth.tools.word_stats_mapping import to_stats_results


def serialize_stats(rows):
    """使用真实接口子模型验证业务结果的序列化。"""
    return {"results": [row.model_dump(mode="json") for row in to_stats_results(rows)]}


def call_stats(service, name, words, username="tester"):
    """执行真实业务服务并映射响应，SQL 与事务检查保留在调用测试中。"""
    return serialize_stats(getattr(service, name)(words, username))
from thoth.dto.word_stats import WordListItem, WordListPreprocessResult, StatsResult
from thoth.mcp_server import mcp
from tests.unit.test_word_repository import ScriptedConnection, database_row

CASES = [(usage_service, "count_word_usage", "usage"), (miss_service, "count_word_miss", "miss")]


def stat_row(value=1, word_id=7):
    """提供经过驱动类型适配的统计记录。"""
    return (1, word_id, value)


def install_backend(monkeypatch, service, *responses):
    """保留真实 DAO 和实体映射，只替换配置及数据库连接。"""
    connection = ScriptedConnection((1, "tester"), *responses)

    @contextmanager
    def connect(settings):
        yield connection

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(operator="tester"))
    monkeypatch.setattr(service, "open_connection", connect)
    return connection


@pytest.mark.parametrize("service,name,kind", CASES)
def test_batch_of_100_uses_four_queries_and_no_explicit_transaction(monkeypatch, service, name, kind):
    words = [f"word{i}" for i in range(100)]
    conn = install_backend(monkeypatch, service,
        [database_row(word, record_id=i+1) for i, word in enumerate(words)], None,
        [stat_row(i+1, i+1) for i in reversed(range(100))])
    rows = call_stats(service, name, words, username="tester")["results"]
    assert len(conn.statements) == 4
    assert conn.commits == conn.rollbacks == 0
    assert [row["word"] for row in rows] == words
    assert [row["counts"] for row in rows] == [{f"{kind}_count": i+1} for i in range(100)]
    user_lookup, lookup, initialize, update = [query for query, _ in conn.statements]
    assert "user_tbl" in user_lookup
    assert all(params["user_id"] == 1 for _, params in conn.statements[2:])
    assert "FOR UPDATE" not in lookup
    assert "SELECT %(user_id)s, id, 0," in initialize and "ON CONFLICT (user_id, word_id) DO NOTHING" in initialize
    assert "status_code <> 'D'" in initialize and "ORDER BY id" in initialize
    assert f"SET {kind}_count = {kind}_count + 1" in update
    assert "status_code <> 'D'" in update and "RETURNING" in update
    assert "created_by =" not in update
    other = "miss" if kind == "usage" else "usage"
    assert all(f"word_{other}_tbl" not in query for query, _ in conn.statements)


@pytest.mark.parametrize("service,name,kind", CASES)
def test_filtered_items_duplicates_missing_deleted_and_changed(monkeypatch, service, name, kind):
    conn = install_backend(monkeypatch, service,
        [database_row("a"), database_row("deleted", status_code="D"), database_row("changed", record_id=8)],
        None, [stat_row(1)])
    values = ["a", None, "", "  ", 123, {}, "a", "missing", "deleted", "changed", "\ud800", "a\x00"]
    rows = call_stats(service, name, values, username="tester")["results"]
    assert [row["index"] for row in rows] == list(range(len(values)))
    assert rows[0]["counts"] == {f"{kind}_count": 1}
    assert all(row["status"] == "skipped" and row["reason"] for row in rows[1:])
    assert "index=0" in rows[6]["reason"]
    assert rows[7]["reason"] == rows[8]["reason"] == "单词不存在。"
    assert "发生变化" in rows[9]["reason"]
    assert rows[10]["word"] is None
    assert conn.statements[1][1] == {"words": ["a", "missing", "deleted", "changed"]}
    assert conn.statements[2][1]["ids"] == [7, 8]
    json.dumps(rows, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("service,name,kind", CASES)
@pytest.mark.parametrize("values", [[], [None, "", " ", 1, {}, "\ud800", "\x00"]])
def test_all_filtered_only_checks_user(monkeypatch, service, name, kind, values):
    conn = install_backend(monkeypatch, service)
    rows = call_stats(service, name, values, username="tester")["results"]
    assert len(rows) == len(values)
    assert all(row["status"] == "skipped" for row in rows)
    assert len(conn.statements) == 1
    assert "user_tbl" in conn.statements[0][0]


@pytest.mark.parametrize("service,name,kind", CASES)
def test_missing_only_does_not_write(monkeypatch, service, name, kind):
    conn = install_backend(monkeypatch, service, [])
    assert call_stats(service, name, ['missing'], username="tester")["results"][0]["status"] == "skipped"
    assert len(conn.statements) == 2


@pytest.mark.parametrize("service,name,kind", CASES)
@pytest.mark.parametrize("stage", ["initialize", "update"])
def test_batch_write_failure_fails_pending_only_without_retry(monkeypatch, service, name, kind, stage):
    responses = [[database_row("a"), database_row("b", record_id=8)]]
    if stage == "update":
        responses.append(None)
    responses.append(psycopg.errors.NumericValueOutOfRange("private SQL"))
    conn = install_backend(monkeypatch, service, *responses)
    rows = call_stats(service, name, ['a', None, 'b', 'a', 'missing'], username="tester")["results"]
    assert [row["status"] for row in rows] == ["failed", "skipped", "failed", "skipped", "skipped"]
    assert all("counts" not in row for row in rows)
    assert "22003" in rows[0]["reason"] and "private" not in rows[0]["reason"]
    assert len(conn.statements) == (4 if stage == "update" else 3)
    assert conn.rollbacks == conn.commits == 0


@pytest.mark.parametrize("service,name,kind", CASES)
def test_initial_lookup_error_is_tool_error(monkeypatch, service, name, kind):
    conn = install_backend(monkeypatch, service, psycopg.OperationalError("private"))
    with pytest.raises(DatabaseError, match="统计操作失败") as exc:
        call_stats(service, name, ['a'], username="tester")
    assert "private" not in str(exc.value) and len(conn.statements) == 2


@pytest.mark.parametrize("service,name,kind", CASES)
@pytest.mark.parametrize("text", ["", "a,b", "{}", "null", "[NaN]", "[Infinity]", '[{"a":1,"a":2}]'])
def test_invalid_batch_does_not_load_config(monkeypatch, service, name, kind, text):
    settings = Mock(side_effect=AssertionError("no config"))
    monkeypatch.setattr(service, "get_settings", settings)
    with pytest.raises(ValueError):
        call_stats(service, name, text, username="tester")
    settings.assert_not_called()


@pytest.mark.parametrize("service,name,kind", CASES)
def test_exact_word_bound_as_parameter(monkeypatch, service, name, kind):
    word = " a'; -- "
    conn = install_backend(monkeypatch, service, [database_row(word)], None, [stat_row()])
    assert call_stats(service, name, [word], username="tester")["results"][0]["word"] == word
    assert conn.statements[1][1] == {"words": [word]}
    assert all(word not in query for query, _ in conn.statements)


@pytest.mark.parametrize("service,name,kind", CASES)
def test_protocol_strict_array_and_structured_result(monkeypatch, service, name, kind):
    install_backend(monkeypatch, service, [database_row("a")], None, [stat_row()])

    async def run():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == {"add_update_words", "count_word_usage", "count_word_miss", "reset_word_miss", "query_words", "query_users"}
            tool = next(tool for tool in tools if tool.name == name)
            assert tool.inputSchema["properties"]["words"]["type"] == "array"
            assert (await client.call_tool_mcp(name, {"username": "tester", "text": ["a"]})).isError
            response = await client.call_tool_mcp(name, {"username": "tester", "words": ["a"]})
            assert not response.isError
            assert response.structuredContent["results"][0]["counts"] == {f"{kind}_count": 1}
    asyncio.run(run())


@pytest.mark.parametrize("existing,expected,status", [(None, None, "skipped"), (0, 0, "skipped"), (9, 0, "updated")])
def test_reset_missing_zero_and_nonzero(monkeypatch, existing, expected, status):
    responses = [database_row(), None if existing is None else stat_row(existing)]
    if existing:
        responses.append(stat_row(0))
    conn = install_backend(monkeypatch, reset_service, *responses)
    row = call_stats(reset_service, "reset_word_miss", ['食べる'], username="tester")["results"][0]
    assert row["status"] == status
    assert row.get("counts") == (None if expected is None else {"miss_count": expected})
    assert len(conn.statements) == (4 if existing else 3)
    assert all("INSERT" not in sql and "word_usage_tbl" not in sql for sql, _ in conn.statements)
    if existing:
        assert "miss_count <> 0" in conn.statements[-1][0]
    assert conn.commits == 1



@pytest.mark.parametrize("record", [None, database_row(status_code="D")])
def test_reset_missing_or_deleted_unchanged(monkeypatch, record):
    conn = install_backend(monkeypatch, reset_service, record)
    result = call_stats(reset_service, "reset_word_miss", ['a'], username="tester")
    assert result == {"results": [{"index": 0, "word": "a", "status": "skipped", "reason": "单词不存在。"}]}
    assert len(conn.statements) == 2


ALL_TOOLS = CASES + [(reset_service, "reset_word_miss", "miss")]


@pytest.mark.parametrize("text", ['', '{}', 'null', 'bad', '[{"word":"a","word":"b"}]', '[NaN]', '[Infinity]', '[' * 2000])
def test_preprocess_rejects_non_list(text):
    with pytest.raises(ValueError, match="words"):
        prepare_word_list(text)


def test_preprocess_preserves_wrappers_identity_and_partition():
    values = ["a", None, "b", "a", "", " ", 1, {"word": "c"}, "\ud800", "\x00", " a "]
    result = prepare_word_list(values)
    assert [item.original_value for item in result.original_items] == values
    assert [item.index for item in result.original_items] == list(range(len(values)))
    assert [item.index for item in result.pending_items] == [0, 2, 10]
    assert all(item is result.original_items[item.index] for item in result.pending_items)
    assert all(not hasattr(item, "entity") for item in result.original_items)
    indices = [item.index for item in result.pending_items] + [item.index for item in result.skipped_results]
    assert sorted(indices) == list(range(len(values)))
    assert "index=0" in next(item.reason for item in result.skipped_results if item.index == 3)
    assert next(item.word for item in result.skipped_results if item.index == 8) is None


def test_dto_list_defaults_are_independent():
    first = WordListPreprocessResult()
    second = WordListPreprocessResult()
    first.original_items.append(WordListItem(0, "a"))
    first.pending_items.append(first.original_items[0])
    first.skipped_results.append(StatsResult(1, None, "skipped", "空"))
    assert second.original_items == second.pending_items == second.skipped_results == []


def test_merge_restores_original_order_without_mutating_inputs():
    result = prepare_word_list([None, 'a', 'a', 'b'])
    original = list(result.original_items)
    pending = list(result.pending_items)
    skipped = list(result.skipped_results)
    executed = [StatsResult(3, "b", "updated", miss_count=2), StatsResult(1, "a", "updated", miss_count=1)]
    merged = merge_stats_results(result, executed)
    assert [item.index for item in merged] == [0, 1, 2, 3]
    assert [item.index for item in executed] == [3, 1]
    assert result.original_items == original and result.pending_items == pending and result.skipped_results == skipped
    assert len(serialize_stats(merged)["results"]) == len(original)


@pytest.mark.parametrize("service,name,kind", ALL_TOOLS)
@pytest.mark.parametrize("values", [[], [None, "", " ", 1, {"word": "a"}, "\ud800", "\x00"]])
def test_shared_filtering_checks_user_without_stat_writes(monkeypatch, service, name, kind, values):
    conn = install_backend(monkeypatch, service)
    result = call_stats(service, name, values, username="tester")
    expected = serialize_stats(prepare_word_list(values).skipped_results)
    assert result == expected
    assert len(conn.statements) == 1
    assert "SELECT id, username FROM user_tbl" in conn.statements[0][0]


@pytest.mark.parametrize("service,name,kind", ALL_TOOLS)
def test_invalid_internal_batch_fails_before_database(monkeypatch, service, name, kind):
    config = Mock(side_effect=AssertionError("no config"))
    monkeypatch.setattr(service, "get_settings", config)
    with pytest.raises(ValueError, match="words"):
        call_stats(service, name, 'not JSON', username="tester")
    config.assert_not_called()


@pytest.mark.parametrize("service,name,kind", ALL_TOOLS)
def test_same_preprocessing_and_original_index_across_tools(monkeypatch, service, name, kind):
    responses = [database_row("a"), stat_row(9), stat_row(0)] if service is reset_service else [[database_row("a")], None, [stat_row(1)]]
    conn = install_backend(monkeypatch, service, *responses)
    rows = call_stats(service, name, [None, 'a', 'a', {'word': 'b'}], username="tester")["results"]
    assert [row["index"] for row in rows] == [0, 1, 2, 3]
    assert [row["status"] for row in rows] == ["skipped", "updated", "skipped", "skipped"]
    assert rows[1]["word"] == "a" and "index=1" in rows[2]["reason"]
    assert rows[3]["word"] is None
    assert len(conn.statements) == 4


def test_reset_failure_rolls_back_only_that_item_and_keeps_indices(monkeypatch):
    conn = install_backend(monkeypatch, reset_service,
        database_row("a"), stat_row(9), psycopg.OperationalError("private"),
        database_row("b"), stat_row(2), stat_row(0))
    rows = call_stats(reset_service, "reset_word_miss", [None, 'a', 'b', 'a'], username="tester")["results"]
    assert [row["index"] for row in rows] == [0, 1, 2, 3]
    assert [row["status"] for row in rows] == ["skipped", "failed", "updated", "skipped"]
    assert "private" not in rows[1]["reason"] and "counts" not in rows[1]
    assert rows[2]["counts"] == {"miss_count": 0}
    assert conn.commits == conn.rollbacks == 1


def test_reset_protocol_accepts_words_and_rejects_old_objects(monkeypatch):
    install_backend(monkeypatch, reset_service, database_row("a"), stat_row(3), stat_row(0))

    async def run():
        async with Client(mcp) as client:
            for arguments in ({"text": ["a"]}, {"words": [{"word": "a"}, "a"]}, {"words": '["a"]'}):
                assert (await client.call_tool_mcp("reset_word_miss", {"username": "tester", **arguments})).isError
            response = await client.call_tool_mcp("reset_word_miss", {"username": "tester", "words": ["a"]})
            assert not response.isError
            assert response.structuredContent["results"] == [
                {"index": 0, "word": "a", "status": "updated", "counts": {"miss_count": 0}}]
    asyncio.run(run())
