"""验证批量计数的过滤、三条 SQL、失败边界及原清零协议。"""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from thoth.service import count_word_usage_service as usage_service
from thoth.service import count_word_miss_service as miss_service
from thoth.service import reset_word_miss_service as reset_service
from thoth.service.word_stats_input_service import parse_word_list_text, merge_stats_results, serialize_stats
from thoth.dto.word_stats import WordListItem, WordListPreprocessResult, StatsResult
from thoth.tools.mcp_tools import mcp
from tests.unit.test_word_repository import ScriptedConnection, database_row, CREATED_AT, UPDATED_AT

CASES = [(usage_service, "count_word_usage", "usage"), (miss_service, "count_word_miss", "miss")]


def stat_row(value=1, word_id=7):
    """提供经过驱动类型适配的统计记录。"""
    return (word_id, value, CREATED_AT, UPDATED_AT, "original", "tester")


def install_backend(monkeypatch, service, *responses):
    """保留真实 DAO 和实体映射，只替换配置及数据库连接。"""
    connection = ScriptedConnection(*responses)

    @contextmanager
    def connect(settings):
        yield connection

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(operator="tester"))
    monkeypatch.setattr(service, "open_connection", connect)
    return connection


@pytest.mark.parametrize("service,name,kind", CASES)
def test_batch_of_100_uses_three_queries_and_no_explicit_transaction(monkeypatch, service, name, kind):
    words = [f"word{i}" for i in range(100)]
    conn = install_backend(monkeypatch, service,
        [database_row(word, record_id=i+1) for i, word in enumerate(words)], None,
        [stat_row(i+1, i+1) for i in reversed(range(100))])
    rows = getattr(service, name)(json.dumps(words))["results"]
    assert len(conn.statements) == 3
    assert conn.commits == conn.rollbacks == 0
    assert [row["word"] for row in rows] == words
    assert [row["counts"] for row in rows] == [{f"{kind}_count": i+1} for i in range(100)]
    lookup, initialize, update = [query for query, _ in conn.statements]
    assert "FOR UPDATE" not in lookup
    assert "SELECT id, 0," in initialize and "ON CONFLICT (word_id) DO NOTHING" in initialize
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
    rows = getattr(service, name)(json.dumps(values))["results"]
    assert [row["index"] for row in rows] == list(range(len(values)))
    assert rows[0]["counts"] == {f"{kind}_count": 1}
    assert all(row["status"] == "skipped" and row["reason"] for row in rows[1:])
    assert "index=0" in rows[6]["reason"]
    assert rows[7]["reason"] == rows[8]["reason"] == "单词不存在。"
    assert "发生变化" in rows[9]["reason"]
    assert rows[10]["word"] is None
    assert conn.statements[0][1] == {"words": ["a", "missing", "deleted", "changed"]}
    assert conn.statements[1][1]["ids"] == [7, 8]
    json.dumps(rows, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("service,name,kind", CASES)
@pytest.mark.parametrize("values", [[], [None, "", " ", 1, {}, "\ud800", "\x00"]])
def test_all_filtered_skips_configuration_and_database(monkeypatch, service, name, kind, values):
    settings = Mock(side_effect=AssertionError("must not load config"))
    monkeypatch.setattr(service, "get_settings", settings)
    rows = getattr(service, name)(json.dumps(values))["results"]
    assert len(rows) == len(values)
    assert all(row["status"] == "skipped" for row in rows)
    settings.assert_not_called()


@pytest.mark.parametrize("service,name,kind", CASES)
def test_missing_only_does_not_write(monkeypatch, service, name, kind):
    conn = install_backend(monkeypatch, service, [])
    assert getattr(service, name)('["missing"]')["results"][0]["status"] == "skipped"
    assert len(conn.statements) == 1


@pytest.mark.parametrize("service,name,kind", CASES)
@pytest.mark.parametrize("stage", ["initialize", "update"])
def test_batch_write_failure_fails_pending_only_without_retry(monkeypatch, service, name, kind, stage):
    responses = [[database_row("a"), database_row("b", record_id=8)]]
    if stage == "update":
        responses.append(None)
    responses.append(psycopg.errors.NumericValueOutOfRange("private SQL"))
    conn = install_backend(monkeypatch, service, *responses)
    rows = getattr(service, name)('["a",null,"b","a","missing"]')["results"]
    assert [row["status"] for row in rows] == ["failed", "skipped", "failed", "skipped", "skipped"]
    assert all("counts" not in row for row in rows)
    assert "22003" in rows[0]["reason"] and "private" not in rows[0]["reason"]
    assert len(conn.statements) == (3 if stage == "update" else 2)
    assert conn.rollbacks == conn.commits == 0


@pytest.mark.parametrize("service,name,kind", CASES)
def test_initial_lookup_error_is_tool_error(monkeypatch, service, name, kind):
    conn = install_backend(monkeypatch, service, psycopg.OperationalError("private"))
    with pytest.raises(ToolError, match="统计操作失败") as exc:
        getattr(service, name)('["a"]')
    assert "private" not in str(exc.value) and len(conn.statements) == 1


@pytest.mark.parametrize("service,name,kind", CASES)
@pytest.mark.parametrize("text", ["", "a,b", "{}", "null", "[NaN]", "[Infinity]", '[{"a":1,"a":2}]'])
def test_invalid_batch_does_not_load_config(monkeypatch, service, name, kind, text):
    settings = Mock(side_effect=AssertionError("no config"))
    monkeypatch.setattr(service, "get_settings", settings)
    with pytest.raises(ToolError):
        getattr(service, name)(text)
    settings.assert_not_called()


@pytest.mark.parametrize("service,name,kind", CASES)
def test_exact_word_bound_as_parameter(monkeypatch, service, name, kind):
    word = " a'; -- "
    conn = install_backend(monkeypatch, service, [database_row(word)], None, [stat_row()])
    assert getattr(service, name)(json.dumps([word]))["results"][0]["word"] == word
    assert conn.statements[0][1] == {"words": [word]}
    assert all(word not in query for query, _ in conn.statements)


@pytest.mark.parametrize("service,name,kind", CASES)
def test_protocol_strict_string_and_structured_result(monkeypatch, service, name, kind):
    install_backend(monkeypatch, service, [database_row("a")], None, [stat_row()])

    async def run():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == {"add_update_words", "count_word_usage", "count_word_miss", "reset_word_miss"}
            tool = next(tool for tool in tools if tool.name == name)
            assert tool.inputSchema["properties"]["text"]["type"] == "string"
            assert (await client.call_tool_mcp(name, {"text": ["a"]})).isError
            response = await client.call_tool_mcp(name, {"text": '["a"]'})
            assert not response.isError
            assert response.structuredContent["results"][0]["counts"] == {f"{kind}_count": 1}
    asyncio.run(run())


@pytest.mark.parametrize("existing,expected,status", [(None, None, "skipped"), (0, 0, "skipped"), (9, 0, "updated")])
def test_reset_missing_zero_and_nonzero(monkeypatch, existing, expected, status):
    responses = [database_row(), None if existing is None else stat_row(existing)]
    if existing:
        responses.append(stat_row(0))
    conn = install_backend(monkeypatch, reset_service, *responses)
    row = reset_service.reset_word_miss('["食べる"]')["results"][0]
    assert row["status"] == status
    assert row.get("counts") == (None if expected is None else {"miss_count": expected})
    assert len(conn.statements) == (3 if existing else 2)
    assert all("INSERT" not in sql and "word_usage_tbl" not in sql for sql, _ in conn.statements)
    if existing:
        assert "miss_count <> 0" in conn.statements[-1][0]
    assert conn.commits == 1



@pytest.mark.parametrize("record", [None, database_row(status_code="D")])
def test_reset_missing_or_deleted_unchanged(monkeypatch, record):
    conn = install_backend(monkeypatch, reset_service, record)
    result = reset_service.reset_word_miss('["a"]')
    assert result == {"results": [{"index": 0, "word": "a", "status": "skipped", "reason": "单词不存在。"}]}
    assert len(conn.statements) == 1


ALL_TOOLS = CASES + [(reset_service, "reset_word_miss", "miss")]


@pytest.mark.parametrize("text", ['', '{}', 'null', 'bad', '[{"word":"a","word":"b"}]', '[NaN]', '[Infinity]', '[' * 2000])
def test_preprocess_stop_returns_message_and_empty_lists(text):
    result = parse_word_list_text(text)
    assert result.status == "stop" and result.message
    assert result.original_items == result.pending_items == result.skipped_results == []


def test_preprocess_preserves_wrappers_identity_and_partition():
    values = ["a", None, "b", "a", "", " ", 1, {"word": "c"}, "\ud800", "\x00", " a "]
    result = parse_word_list_text(json.dumps(values))
    assert result.status == "continue" and result.message is None
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
    first = WordListPreprocessResult("continue")
    second = WordListPreprocessResult("continue")
    first.original_items.append(WordListItem(0, "a"))
    first.pending_items.append(first.original_items[0])
    first.skipped_results.append(StatsResult(1, None, "skipped", "空"))
    assert second.original_items == second.pending_items == second.skipped_results == []


def test_merge_restores_original_order_without_mutating_inputs():
    result = parse_word_list_text('[null,"a","a","b"]')
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
def test_shared_filtering_without_configuration_or_connection(monkeypatch, service, name, kind, values):
    config = Mock(side_effect=AssertionError("no config"))
    connect = Mock(side_effect=AssertionError("no connection"))
    monkeypatch.setattr(service, "get_settings", config)
    monkeypatch.setattr(service, "open_connection", connect)
    result = getattr(service, name)(json.dumps(values))
    expected = serialize_stats(parse_word_list_text(json.dumps(values)).skipped_results)
    assert result == expected
    config.assert_not_called()
    connect.assert_not_called()


@pytest.mark.parametrize("service,name,kind", ALL_TOOLS)
def test_stop_becomes_tool_error_without_database(monkeypatch, service, name, kind):
    config = Mock(side_effect=AssertionError("no config"))
    monkeypatch.setattr(service, "get_settings", config)
    with pytest.raises(ToolError, match="JSON"):
        getattr(service, name)('not JSON')
    config.assert_not_called()


@pytest.mark.parametrize("service,name,kind", ALL_TOOLS)
def test_same_preprocessing_and_original_index_across_tools(monkeypatch, service, name, kind):
    responses = [database_row("a"), stat_row(9), stat_row(0)] if service is reset_service else [[database_row("a")], None, [stat_row(1)]]
    conn = install_backend(monkeypatch, service, *responses)
    rows = getattr(service, name)('[null,"a","a",{"word":"b"}]')["results"]
    assert [row["index"] for row in rows] == [0, 1, 2, 3]
    assert [row["status"] for row in rows] == ["skipped", "updated", "skipped", "skipped"]
    assert rows[1]["word"] == "a" and "index=1" in rows[2]["reason"]
    assert rows[3]["word"] is None
    assert len(conn.statements) == 3


def test_reset_failure_rolls_back_only_that_item_and_keeps_indices(monkeypatch):
    conn = install_backend(monkeypatch, reset_service,
        database_row("a"), stat_row(9), psycopg.OperationalError("private"),
        database_row("b"), stat_row(2), stat_row(0))
    rows = reset_service.reset_word_miss('[null,"a","b","a"]')["results"]
    assert [row["index"] for row in rows] == [0, 1, 2, 3]
    assert [row["status"] for row in rows] == ["skipped", "failed", "updated", "skipped"]
    assert "private" not in rows[1]["reason"] and "counts" not in rows[1]
    assert rows[2]["counts"] == {"miss_count": 0}
    assert conn.commits == conn.rollbacks == 1


def test_reset_protocol_accepts_string_list_and_skips_old_objects(monkeypatch):
    install_backend(monkeypatch, reset_service, database_row("a"), stat_row(3), stat_row(0))

    async def run():
        async with Client(mcp) as client:
            assert (await client.call_tool_mcp("reset_word_miss", {"text": ["a"]})).isError
            response = await client.call_tool_mcp("reset_word_miss", {"text": '[{"word":"a"},"a"]'})
            assert not response.isError
            rows = response.structuredContent["results"]
            assert rows[0]["status"] == "skipped"
            assert rows[1] == {"index": 1, "word": "a", "status": "updated", "counts": {"miss_count": 0}}
    asyncio.run(run())
