"""Exercise the public FastMCP interface over its in-memory transport."""

import asyncio
import importlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastmcp import Client

from thoth.tools import word_tools as mcp_server
from thoth.db.connection import DatabaseError
from thoth.dao.word_tbl_mapper import MissingWordFieldsError
from thoth.dto.word import SaveResult
from thoth.entity import WordEntity


@pytest.fixture
def backend(monkeypatch):
    settings = SimpleNamespace(operator="test-operator")
    get_settings = Mock(return_value=settings)
    connection = object()
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection
    open_connection = Mock(return_value=connection_context)
    repository = Mock(
        find_existing_words=Mock(return_value=[]),
        save=Mock(return_value=SaveResult(status="created")),
    )
    repository_factory = Mock(return_value=repository)
    monkeypatch.setattr(mcp_server, "get_settings", get_settings)
    monkeypatch.setattr(mcp_server, "open_connection", open_connection)
    monkeypatch.setattr(mcp_server, "WordTblMapper", repository_factory)
    return SimpleNamespace(
        settings=settings, get_settings=get_settings, open_connection=open_connection,
        connection=connection, repository=repository, repository_factory=repository_factory,
    )


def call_save_words(text):
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool_mcp("save_words", {"text": text})
    return asyncio.run(run())


def test_import_does_not_read_configuration_or_connect(monkeypatch):
    from thoth.common import config
    from thoth.db import connection

    get_settings = Mock(side_effect=AssertionError("must not load real configuration"))
    open_connection = Mock(side_effect=AssertionError("must not connect during import"))
    # reload resolves these imported names again, so patch their source modules too.
    with monkeypatch.context() as patch:
        patch.setattr(config, "get_settings", get_settings)
        patch.setattr(connection, "open_connection", open_connection)
        importlib.reload(mcp_server)
        get_settings.assert_not_called()
        open_connection.assert_not_called()
    importlib.reload(mcp_server)


def test_only_save_words_is_exposed_and_description_explains_default(backend):
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.list_tools()
    tools = asyncio.run(run())

    assert [tool.name for tool in tools] == ["save_words"]
    tool = tools[0]
    assert tool.inputSchema["required"] == ["text"]
    assert set(tool.inputSchema["properties"]) == {"text"}
    assert tool.inputSchema["properties"]["text"]["type"] == "string"
    description = tool.description
    assert "operation" in description
    assert "省略" in description and "默认" in description and "create" in description
    for field in ("word", "common_form", "hiragana", "meaning", "action"):
        assert field in description
    backend.get_settings.assert_not_called()
    backend.open_connection.assert_not_called()


@pytest.mark.parametrize("text", ["not json", "{}", "[]"])
def test_invalid_json_is_protocol_error_before_database_access(backend, text):
    result = call_save_words(text)
    assert result.isError is True
    backend.get_settings.assert_not_called()
    backend.open_connection.assert_not_called()


def test_tool_returns_structured_per_word_results(backend):
    backend.repository.save.return_value = SaveResult(
        status="created",
        entity=WordEntity(
            id=1, word="食べる", common_form="食べる", hiragana="たべる", meaning="吃",
            status_code="A", created_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
            created_by="test-operator", updated_by="test-operator",
        ),
    )
    result = call_save_words(json.dumps([
        {"word": "食べる", "common_form": "食べる", "hiragana": "たべる", "meaning": "吃"},
        {"word": "飲む", "operation": {"action": "delete"}},
    ]))

    assert result.isError is False
    assert result.structuredContent == {
        "results": [
            {"index": 0, "word": "食べる", "status": "created"},
            {
                "index": 1, "word": "飲む", "status": "failed",
                "reason": "operation.action 仅允许 create 或 update。",
            },
        ],
    }
    backend.get_settings.assert_called_once_with()
    backend.open_connection.assert_called_once_with(backend.settings)
    backend.repository_factory.assert_called_once_with(backend.connection, operator="test-operator")
    backend.repository.find_existing_words.assert_called_once_with(["食べる"])
    backend.repository.save.assert_called_once_with(
        WordEntity(word="食べる", common_form="食べる", hiragana="たべる", meaning="吃"),
        action="create", exists=False,
    )


def test_tool_serializes_optional_reason_and_missing_fields_only_when_present(backend):
    missing_fields = MissingWordFieldsError(("common_form", "hiragana"))
    backend.repository.find_existing_words.return_value = [WordEntity(word="食べる")]
    backend.repository.save.side_effect = [
        SaveResult(status="skipped", reason="单词已存在。"),
        missing_fields,
        SaveResult(status="created"),
    ]

    result = call_save_words(json.dumps([
        {"word": "食べる"},
        {"word": "飲む", "meaning": "喝"},
        {"word": "走る", "common_form": "走る", "hiragana": "はしる", "meaning": "跑"},
    ]))

    assert result.isError is False
    assert result.structuredContent == {
        "results": [
            {"index": 0, "word": "食べる", "status": "skipped", "reason": "单词已存在。"},
            {
                "index": 1, "word": "飲む", "status": "failed",
                "reason": str(missing_fields), "fields": ["common_form", "hiragana"],
            },
            {"index": 2, "word": "走る", "status": "created"},
        ],
    }


def test_database_connection_failure_is_protocol_error(backend):
    backend.open_connection.side_effect = DatabaseError("连接 PostgreSQL 失败，请检查配置。")
    result = call_save_words('[{"word":"食べる"}]')
    assert result.isError is True
    assert "连接 PostgreSQL 失败" in str(result)
    backend.repository_factory.assert_not_called()


def test_batch_lookup_failure_is_protocol_error_without_writes(backend):
    backend.repository.find_existing_words.side_effect = DatabaseError("查询单词失败，请稍后重试。")
    result = call_save_words(json.dumps([
        {"word": "食べる", "common_form": "食べる", "hiragana": "たべる", "meaning": "吃"},
        {"word": "飲む", "meaning": "喝", "operation": {"action": "update"}},
    ]))

    assert result.isError is True
    assert "查询单词失败" in str(result)
    backend.repository.find_existing_words.assert_called_once_with(["食べる", "飲む"])
    backend.repository.save.assert_not_called()


def test_surrogate_word_returns_serializable_failure_without_disrupting_valid_word(backend):
    result = call_save_words(json.dumps([
        {"word": "\ud800"},
        {"word": "飲む", "common_form": "飲む", "hiragana": "のむ", "meaning": "喝"},
    ]))

    assert result.isError is False
    rows = result.structuredContent["results"]
    assert [row["status"] for row in rows] == ["failed", "created"]
    assert rows[0]["word"] is None
    assert rows[0]["index"] == 0
    json.dumps(result.structuredContent, ensure_ascii=False).encode("utf-8")
    backend.repository.find_existing_words.assert_called_once_with(["飲む"])
    backend.repository.save.assert_called_once()
    assert backend.repository.save.call_args.args[0].word == "飲む"


def test_configuration_failure_is_protocol_error(backend):
    backend.get_settings.side_effect = ValueError("缺少 THOTH_PG_DSN。")
    result = call_save_words('[{"word":"食べる"}]')
    assert result.isError is True
    assert "THOTH_PG_DSN" in str(result)
    backend.open_connection.assert_not_called()


def test_text_parameter_does_not_accept_array(backend):
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool_mcp("save_words", {"text": [{"word": "食べる"}]})
    result = asyncio.run(run())
    assert result.isError is True
    backend.get_settings.assert_not_called()
