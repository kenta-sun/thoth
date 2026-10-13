"""验证新接口边界、Schema、响应投影及分层依赖，不使用真实数据库。"""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import jsonschema
import pytest
from fastmcp import Client
from pydantic import TypeAdapter

from thoth.mcp_server import mcp
from thoth.service import (
    add_update_words_service, count_word_usage_service, count_word_miss_service,
    reset_word_miss_service, query_words_service, query_users_service,
)
from thoth.dto.request.add_update_words_request import WordWriteInput
from thoth.dto.request.query_words_request import WordQueryInput
from thoth.dto.query_words import QueryWordResult
from thoth.dto.word import WordWriteCommand, WordBatchResult, WordItemResult
from thoth.dto.word_stats import StatsResult
from thoth.entity import WordEntity
from thoth.tools.add_update_words_tools import to_write_commands
from thoth.tools.query_words_tools import to_query_request


@pytest.mark.parametrize("name,service,parameter", [
    ("count_word_usage", count_word_usage_service, "words"),
    ("count_word_miss", count_word_miss_service, "words"),
    ("reset_word_miss", reset_word_miss_service, "words"),
    ("add_update_words", add_update_words_service, "words"),
    ("query_words", query_words_service, "query"),
])
def test_protocol_structure_errors_never_enter_service(monkeypatch, name, service, parameter):
    called = Mock(side_effect=AssertionError("结构错误不得调用业务层"))
    monkeypatch.setattr(service, name, called)
    cases = [None, "[]", 1]
    if name == "add_update_words":
        good = {"word": "a", "tags": ["v"]}
        cases += [[], [good, {**good, "action": "delete"}],
                  [good, {"word": 1, "tags": ["v"]}],
                  [{**good, "operation": {"action": "create"}}], [{**good, "tags": []}]]
    elif name == "query_words":
        cases += [{"where": {"word": "a"}}, {"sort": [["word", "asc"]]},
                  {"where": {"miss_count": {"eq": True}}}, {"where": {"word": {}}},
                  {"where": {"word": {"eq": None}}}, {"limit": True}, {"limit": 1.0},
                  {"where": None}, {"fields": []}, {"sort": []}, {"limit": None},
                  {"sort": [{"field": "word", "direction": "asc"}, {"field": "word", "direction": "desc"}]}]
    else:
        cases += [["a", 1], ["a", None], ["a", {"word": "b"}], [True]]

    async def run():
        async with Client(mcp) as client:
            for value in cases:
                result = await client.call_tool_mcp(name, {"username": "tester", parameter: value})
                assert result.isError, (name, value)
            assert (await client.call_tool_mcp(name, {"username": "tester", "text": "[]"})).isError
            assert (await client.call_tool_mcp(name, {"username": "tester"})).isError
    asyncio.run(run())
    called.assert_not_called()


def test_input_mapping_uses_only_internal_types_and_preserves_defaults():
    source = WordWriteInput(word="a", tags=["v"])
    command, = to_write_commands([source])
    assert type(command) is WordWriteCommand
    assert command.action == "create" and command.tags == ("v",)
    source.tags.append("n")
    assert command.tags == ("v",)
    query = WordQueryInput.model_validate({"where": {"word": {"eq": " a "}, "miss_count": {"in": [0, 3]}},
                                         "sort": [{"field": "word", "direction": "desc"}]})
    internal = to_query_request(query)
    assert [(item.field, item.operator, item.value) for item in internal.conditions] == [
        ("word", "eq", " a "), ("miss_count", "in", (0, 3))]
    assert internal.sort == (("word", "desc"),) and internal.limit is None


@pytest.mark.parametrize("value", [True, 1.0, "1", -1, 2**63])
def test_query_counts_are_strict_bigints(value):
    with pytest.raises(ValueError):
        WordQueryInput.model_validate({"where": {"miss_count": {"eq": value}}})


def test_every_tool_output_matches_schema_and_projection_keeps_null(monkeypatch):
    monkeypatch.setattr(add_update_words_service, "add_update_words", Mock(return_value=WordBatchResult([
        WordItemResult(0, None, "failed", "无效文本"), WordItemResult(1, "a", "created")
    ])))
    for service, name in [(count_word_usage_service, "count_word_usage"),
                          (count_word_miss_service, "count_word_miss"),
                          (reset_word_miss_service, "reset_word_miss")]:
        field = "usage_count" if name == "count_word_usage" else "miss_count"
        monkeypatch.setattr(service, name, Mock(return_value=[
            StatsResult(0, "a", "updated", **{field: 0}), StatsResult(1, None, "skipped", "无效文本")]))
    monkeypatch.setattr(query_words_service, "query_words", Mock(return_value=[QueryWordResult(word=WordEntity(meaning=None))]))
    monkeypatch.setattr(query_users_service, "query_users", Mock(return_value=[]))

    async def run():
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            for name, tool in tools.items():
                if name == "query_users":
                    args = {}
                elif name == "query_words":
                    args = {"username": "tester", "query": {"fields": ["meaning"]}}
                elif name == "add_update_words":
                    args = {"username": "tester", "words": [{"word": "a", "tags": ["v"]}]}
                else:
                    args = {"username": "tester", "words": ["a"]}
                result = await client.call_tool_mcp(name, args)
                assert not result.isError, str(result)
                jsonschema.validate(result.structuredContent, tool.outputSchema)
                rows = result.structuredContent["results"]
                if name == "query_words":
                    assert rows == [{"meaning": None}]
                elif name == "add_update_words":
                    assert rows[0]["word"] is None and "fields" not in rows[0]
                    assert rows[1] == {"index": 1, "word": "a", "status": "created"}
                elif name != "query_users":
                    assert list(rows[0]["counts"].values()) == [0]
                    assert "reason" not in rows[0] and "counts" not in rows[1]
                    assert rows[1]["word"] is None
    asyncio.run(run())


def test_business_layers_do_not_import_protocol_models_or_fastmcp():
    root = Path(__file__).resolve().parents[2] / "src/thoth"
    for folder in ("service", "dao", "entity"):
        for path in (root / folder).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                imports = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                           [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                assert not any(name.startswith(("fastmcp", "thoth.tools", "thoth.dto.request", "thoth.dto.response"))
                               for name in imports), path
