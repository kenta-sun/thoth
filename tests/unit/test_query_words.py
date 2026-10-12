"""查询协议测试：验证严格解析、SQL 参数隔离、按需关联和 MCP 边界。"""

import asyncio
import importlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from thoth.common.query_words import QUERY_FIELDS
from thoth.common.tags import TAG_DEFINITIONS, TAG_OPTIONS_DESCRIPTION
from thoth.dao.word_tbl_mapper import WORD_QUERY_SPEC, _query_row_factory
from thoth.descriptions import add_update_words_descriptions, query_words_descriptions
from thoth.dto.query_words import QueryCondition, QueryRequest
from thoth.service import query_words_service as service
from thoth.tools.mcp_tools import mcp
from thoth.utils.generate_tag_sql import render_tag_sql
from thoth.utils.sql_query_builder import build_query


def build(raw):
    """使用真实解析器和 Mapper 配置构建查询，不访问数据库。"""
    return build_query(service.parse_query(json.dumps(raw)), WORD_QUERY_SPEC)


def test_default_query_and_single_field_projection():
    request = service.parse_query('{}')
    assert request.fields == QUERY_FIELDS and request.limit is None
    query = build({})
    assert "w.status_code <> 'D'" in query.sql and "LIMIT" not in query.sql
    assert query.sql.endswith("ORDER BY w.id ASC")
    assert "COALESCE(u.usage_count, 0)" in query.sql
    assert "COALESCE(m.miss_count, 0)" in query.sql
    assert "EXISTS" not in query.sql
    for field in ("created_at", "updated_at", "created_by", "updated_by"):
        assert field not in query.sql
    projected = build({"fields": ["common_form"]})
    assert projected.sql.startswith('SELECT w.common_form AS "common_form"')
    assert "JOIN" not in projected.sql and "word_tag_tbl" not in projected.sql


def test_combination_binds_values_and_joins_unprojected_sort_and_filter():
    pattern = "%'; DROP TABLE word_tbl; --%"
    query = build({
        "fields": ["word"],
        "where": {"tags": {"in": ["v", "n"]}, "common_form": {"like": pattern},
                  "usage_count": {"gte": 0, "lte": 5}},
        "sort": [["miss_count", "desc"], ["usage_count", "asc"]], "limit": 100,
    })
    assert query.params == {"p0": ["v", "n"], "p1": pattern, "p2": 0, "p3": 5, "limit": 100}
    assert pattern not in query.sql
    assert "ft.tag_code = ANY(%(p0)s)" in query.sql
    assert "w.common_form LIKE %(p1)s" in query.sql
    assert "COALESCE(u.usage_count, 0) >= %(p2)s" in query.sql
    assert "COALESCE(u.usage_count, 0) <= %(p3)s" in query.sql
    assert "ORDER BY COALESCE(m.miss_count, 0) DESC, COALESCE(u.usage_count, 0) ASC, w.id ASC" in query.sql
    assert query.sql.endswith("LIMIT %(limit)s")
    assert query.sql.count("LEFT JOIN word_usage_tbl") == 1
    assert query.sql.count("LEFT JOIN word_miss_tbl") == 1


@pytest.mark.parametrize("field,operation,value,fragment", [
    ("word", "in", ["a", "b"], "w.word = ANY(%(p0)s)"),
    ("usage_count", "in", [0, 1], "COALESCE(u.usage_count, 0) = ANY(%(p0)s)"),
    ("miss_count", "gt", 1, "COALESCE(m.miss_count, 0) > %(p0)s"),
    ("miss_count", "lt", 4, "COALESCE(m.miss_count, 0) < %(p0)s"),
    ("common_form", "like", "食%", "w.common_form LIKE %(p0)s"),
])
def test_operator_sql(field, operation, value, fragment):
    query = build({"where": {field: {operation: value}}})
    assert fragment in query.sql and query.params == {"p0": value}


def test_exact_values_and_empty_text_are_preserved():
    query = build({"where": {"word": "  食べる  ", "common_form": "", "usage_count": 0}})
    assert query.params == {"p0": "  食べる  ", "p1": "", "p2": 0}
    assert "w.word = %(p0)s" in query.sql
    request = service.parse_query('{"where":{"common_form":{"in":["食べる"],"like":"%る"}}}')
    assert len(request.conditions) == 2


@pytest.mark.parametrize("raw", [
    [], None, {"other": 1}, {"where": None}, {"where": []},
    {"where": {"status_code": "D"}}, {"where": {"word": {}}},
    {"where": {"word": {"eq": "a"}}}, {"where": {"word": {"like": "%"}}},
    {"where": {"tags": "v"}}, {"where": {"tags": {"in": []}}},
    {"where": {"word": ["a"]}}, {"where": {"word": None}},
    {"where": {"word": {"in": [None]}}}, {"where": {"word": "\x00"}},
    {"where": {"word": "\ud800"}}, {"where": {"usage_count": True}},
    {"where": {"usage_count": -1}}, {"where": {"usage_count": 1.5}},
    {"where": {"usage_count": 2**63}}, {"where": {"usage_count": {"in": ["0"]}}},
    {"where": {"miss_count": {"like": "%"}}}, {"where": {"common_form": {"like": []}}},
    {"fields": []}, {"fields": None}, {"fields": "word"}, {"fields": [{}]},
    {"fields": ["created_at"]}, {"fields": ["word", "word"]},
    {"sort": []}, {"sort": None}, {"sort": [["tags", "asc"]]},
    {"sort": [["word", "ASC"]]}, {"sort": [["word", {}]]}, {"sort": [1]},
    {"sort": [["word", "asc"], ["word", "desc"]]}, {"sort": [["created_at", "desc"]]},
    {"limit": None}, {"limit": True}, {"limit": 0}, {"limit": -1}, {"limit": 1.0}, {"limit": 2**63},
])
def test_invalid_requests_fail_before_config(monkeypatch, raw):
    settings = Mock(side_effect=AssertionError("must not read config"))
    monkeypatch.setattr(service, "get_settings", settings)
    with pytest.raises(ToolError):
        service.query_words(json.dumps(raw))
    settings.assert_not_called()


@pytest.mark.parametrize("text", [None, {}, "", "{", '{"where":{},"where":{}}',
                                      '{"limit":NaN}', '{"limit":Infinity}', "[" * 2000])
def test_invalid_json(text):
    with pytest.raises(ValueError):
        service.parse_query(text)


@pytest.mark.parametrize("query_request", [
    QueryRequest(("word; SELECT 1",)),
    QueryRequest(("word",), (QueryCondition("word", "like", "%"),)),
    QueryRequest(("word",), sort=(("word", "desc; SELECT 1"),)),
    QueryRequest(("word",), sort=(("tags", "asc"),)),
    QueryRequest(("word",), limit=True),
])
def test_builder_rechecks_sql_structure(query_request):
    with pytest.raises(ValueError):
        build_query(query_request, WORD_QUERY_SPEC)


def test_projection_maps_table_entities_and_serializes_only_selected_fields():
    fields = ("common_form", "tags", "usage_count", "miss_count")
    factory = _query_row_factory(SimpleNamespace(description=[SimpleNamespace(name=name) for name in fields]))
    row = factory(("食べる", ["v", "v2"], 0, 2))
    assert row.word.word is None and row.word.created_at is None
    assert row.usage.word_id is None and row.miss.miss_count == 2
    assert service.serialize_query([row], fields) == {"results": [
        {"common_form": "食べる", "tags": ["v", "v2"], "usage_count": 0, "miss_count": 2}]}
    assert service.serialize_query([], fields) == {"results": []}


def test_protocol_schema_response_and_errors(monkeypatch):
    mapper = Mock(query_words=Mock(return_value=[]))
    monkeypatch.setattr(service, "get_settings", lambda: object())
    monkeypatch.setattr(service, "WordTblMapper", Mock(return_value=mapper))

    @contextmanager
    def connect(settings):
        """提供占位连接，实际 Mapper 由 mock 接管。"""
        yield object()

    monkeypatch.setattr(service, "open_connection", connect)

    async def run():
        """走真实 MCP 内存传输，校验字符串入参及错误转换。"""
        async with Client(mcp) as client:
            tool = next(tool for tool in await client.list_tools() if tool.name == "query_words")
            assert tool.inputSchema["required"] == ["text"]
            assert tool.inputSchema["properties"]["text"]["type"] == "string"
            assert (await client.call_tool_mcp("query_words", {"text": {}})).isError
            result = await client.call_tool_mcp("query_words", {"text": "{}"})
            assert not result.isError and result.structuredContent == {"results": []}
            mapper.query_words.side_effect = psycopg.errors.UndefinedTable("private SQL or credentials")
            result = await client.call_tool_mcp("query_words", {"text": "{}"})
            assert result.isError and "private SQL" not in str(result)
    asyncio.run(run())


def test_tags_single_source_and_description_import_does_not_connect(monkeypatch):
    from thoth.db import connection
    fail = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(connection, "open_connection", fail)
    for module, name in [(add_update_words_descriptions, "ADD_UPDATE_WORDS_DESCRIPTION"),
                         (query_words_descriptions, "QUERY_WORDS_DESCRIPTION")]:
        importlib.reload(module)
        text = getattr(module, name)
        assert text.count(TAG_OPTIONS_DESCRIPTION) == 1
        for tag in TAG_DEFINITIONS:
            assert f"{tag.code}={tag.zh_name}" in text
    assert len({tag.code for tag in TAG_DEFINITIONS}) == len(TAG_DEFINITIONS)
    root = Path(__file__).resolve().parents[2]
    assert (root / "sql/dml/dml__tag_tbl.sql").read_text() == render_tag_sql()
    fail.assert_not_called()
