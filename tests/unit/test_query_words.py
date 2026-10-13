"""查询协议测试：验证结构化模型、SQL 参数隔离、按需关联和 MCP 边界。"""

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
from thoth.dto.request import add_update_words_request, query_words_request
from thoth.dto.request.query_words_request import WordQueryInput
from thoth.tools.query_words_tools import to_query_request, to_query_response
from thoth.dto.query_words import QueryCondition, QueryRequest
from thoth.service import query_words_service as service
from thoth.mcp_server import mcp
from thoth.utils.generate_tag_sql import render_tag_sql
from thoth.utils.sql_query_builder import build_query


def build(raw):
    """使用真实请求模型、入口映射和 Mapper 配置构建查询，不访问数据库。"""
    return build_query(to_query_request(WordQueryInput.model_validate(raw)), WORD_QUERY_SPEC)


def test_default_query_and_single_field_projection():
    request = to_query_request(WordQueryInput())
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
        "sort": [{"field": "miss_count", "direction": "desc"}, {"field": "usage_count", "direction": "asc"}], "limit": 100,
    })
    assert query.params == {"p0": pattern, "p1": ["v", "n"], "p2": 0, "p3": 5, "limit": 100}
    assert pattern not in query.sql
    assert "ft.tag_code = ANY(%(p1)s)" in query.sql
    assert "w.common_form LIKE %(p0)s" in query.sql
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
    query = build({"where": {"word": {"eq": "  食べる  "}, "common_form": {"eq": ""}, "usage_count": {"eq": 0}}})
    assert query.params == {"p0": "  食べる  ", "p1": "", "p2": 0}
    assert "w.word = %(p0)s" in query.sql
    request = to_query_request(WordQueryInput.model_validate({"where":{"common_form":{"in":["食べる"],"like":"%る"}}}))
    assert len(request.conditions) == 2


@pytest.mark.parametrize("raw", [
    [], None, {"other": 1}, {"where": None}, {"where": []},
    {"where": {"status_code": "D"}}, {"where": {"word": {}}},
    {"where": {"word": "a"}}, {"where": {"word": {"like": "%"}}},
    {"where": {"tags": "v"}}, {"where": {"tags": {"in": []}}},
    {"where": {"word": ["a"]}}, {"where": {"word": None}},
    {"where": {"word": {"in": [None]}}}, {"where": {"word": "\x00"}},
    {"where": {"word": "\ud800"}}, {"where": {"usage_count": True}},
    {"where": {"usage_count": -1}}, {"where": {"usage_count": 1.5}},
    {"where": {"usage_count": 2**63}}, {"where": {"usage_count": {"in": ["0"]}}},
    {"where": {"miss_count": {"like": "%"}}}, {"where": {"common_form": {"like": []}}},
    {"fields": []}, {"fields": None}, {"fields": "word"}, {"fields": [{}]},
    {"fields": ["created_at"]}, {"fields": ["word", "word"]},
    {"sort": []}, {"sort": None}, {"sort": [{"field": "tags", "direction": "asc"}]},
    {"sort": [{"field": "word", "direction": "ASC"}]}, {"sort": [["word", {}]]}, {"sort": [1]},
    {"sort": [{"field": "word", "direction": "asc"}, {"field": "word", "direction": "desc"}]}, {"sort": [{"field": "created_at", "direction": "desc"}]},
    {"limit": None}, {"limit": True}, {"limit": 0}, {"limit": -1}, {"limit": 1.0}, {"limit": 2**63},
])
def test_invalid_requests_fail_before_config(monkeypatch, raw):
    settings = Mock(side_effect=AssertionError("must not read config"))
    monkeypatch.setattr(service, "get_settings", settings)
    with pytest.raises(ValueError):
        WordQueryInput.model_validate(raw)
    settings.assert_not_called()


@pytest.mark.parametrize("text", [None, [], "", "{", '{"where":{},"where":{}}',
                                      '{"limit":NaN}', '{"limit":Infinity}', "[" * 2000])
def test_query_requires_native_object(text):
    with pytest.raises(ValueError):
        WordQueryInput.model_validate(text)


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
    assert to_query_response([row], fields).model_dump(mode="json") == {"results": [
        {"common_form": "食べる", "tags": ["v", "v2"], "usage_count": 0, "miss_count": 2}]}
    assert to_query_response([], fields).model_dump(mode="json") == {"results": []}


def test_protocol_schema_response_and_errors(monkeypatch):
    monkeypatch.setattr(service, "require_user", Mock(return_value=SimpleNamespace(id=1)))
    mapper = Mock(query_words=Mock(return_value=[]))
    monkeypatch.setattr(service, "get_settings", lambda: object())
    monkeypatch.setattr(service, "WordTblMapper", Mock(return_value=mapper))

    @contextmanager
    def connect(settings):
        """提供占位连接，实际 Mapper 由 mock 接管。"""
        yield object()

    monkeypatch.setattr(service, "open_connection", connect)

    async def run():
        """走真实 MCP 内存传输，校验对象入参及错误转换。"""
        async with Client(mcp) as client:
            tool = next(tool for tool in await client.list_tools() if tool.name == "query_words")
            assert tool.inputSchema["required"] == ["username", "query"]
            assert tool.inputSchema["properties"]["query"]["type"] == "object"
            assert (await client.call_tool_mcp("query_words", {"username": "tester", "text": {}})).isError
            result = await client.call_tool_mcp("query_words", {"username": "tester", "query": {}})
            assert not result.isError and result.structuredContent == {"results": []}
            mapper.query_words.side_effect = psycopg.errors.UndefinedTable("private SQL or credentials")
            result = await client.call_tool_mcp("query_words", {"username": "tester", "query": {}})
            assert result.isError and "private SQL" not in str(result)
    asyncio.run(run())


def test_tags_single_source_and_description_import_does_not_connect(monkeypatch):
    from thoth.db import connection
    fail = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(connection, "open_connection", fail)
    for module, model in [(add_update_words_request, "WordWriteInput"),
                          (query_words_request, "WordQueryInput")]:
        # 模型仅包含静态标签元数据，导入和生成 Schema 均不得查询数据库。
        schema = json.dumps(getattr(module, model).model_json_schema(), ensure_ascii=False)
        assert TAG_OPTIONS_DESCRIPTION in schema
        for tag in TAG_DEFINITIONS:
            assert f"{tag.code}={tag.zh_name}" in schema
    assert len({tag.code for tag in TAG_DEFINITIONS}) == len(TAG_DEFINITIONS)
    root = Path(__file__).resolve().parents[2]
    assert (root / "sql/dml/dml__tag_tbl.sql").read_text() == render_tag_sql()
    fail.assert_not_called()
