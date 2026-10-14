"""通过 FastMCP 内存传输验证工具注册、参数校验和协议响应。"""

import asyncio
import importlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastmcp import Client

from thoth import mcp_server
from thoth.service import add_update_words_service
from thoth.db.connection import DatabaseError
from thoth.service.add_update_words_service import MissingWordFieldsError
from thoth.entity import WordEntity, TagEntity


def test_main_starts_http_with_local_host_protection(monkeypatch):
    """入口使用 HTTP 及本机 Host/Origin 保护，不启动 stdio 服务。"""
    monkeypatch.setattr(mcp_server, "get_settings", Mock())
    run = Mock()
    monkeypatch.setattr(mcp_server.mcp, "run", run)
    mcp_server.main()
    run.assert_called_once_with(
        transport="http", path="/mcp", show_banner=False, log_level="INFO",
        host_origin_protection=True,
        allowed_hosts=["localhost", "127.0.0.1"],
        allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
    )


def test_main_rejects_missing_configuration_before_listening(monkeypatch):
    """配置校验失败时不开放 HTTP 端口。"""
    monkeypatch.setattr(mcp_server, "get_settings", Mock(side_effect=ValueError("缺少配置")))
    run = Mock()
    monkeypatch.setattr(mcp_server.mcp, "run", run)
    with pytest.raises(ValueError, match="缺少配置"):
        mcp_server.main()
    run.assert_not_called()


@pytest.fixture
def backend(monkeypatch):
    """替换配置、连接和 Mapper，保留真实 Service 流程以验证 MCP 协议结果。"""
    settings = SimpleNamespace()
    get_settings = Mock(return_value=settings)
    connection = MagicMock()
    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection
    open_connection = Mock(return_value=connection_context)
    repository = Mock(
        find_existing_words=Mock(return_value=[]),
        insert=Mock(return_value=WordEntity(id=1)),
        update=Mock(return_value=WordEntity(id=1)),
    )
    repository_factory = Mock(return_value=repository)
    monkeypatch.setattr(add_update_words_service, "get_settings", get_settings)
    monkeypatch.setattr(add_update_words_service, "open_connection", open_connection)
    monkeypatch.setattr(add_update_words_service, "WordTblMapper", repository_factory)
    monkeypatch.setattr(add_update_words_service, "TagTblMapper", Mock(return_value=Mock(
        find_by_codes=Mock(side_effect=lambda codes: [TagEntity(code=code) for code in codes])
    )))
    monkeypatch.setattr(add_update_words_service, "WordTagTblMapper", Mock())
    return SimpleNamespace(
        settings=settings, get_settings=get_settings, open_connection=open_connection,
        connection=connection, repository=repository, repository_factory=repository_factory,
    )


def call_add_update_words(words):
    """通过内存客户端调用工具，返回包含结构化内容或工具错误的协议响应。"""
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool_mcp("add_update_words", {"words": words})
    return asyncio.run(run())


def test_import_does_not_read_configuration_or_connect(monkeypatch):
    from thoth.common import config
    from thoth.db import connection

    get_settings = Mock(side_effect=AssertionError("must not load real configuration"))
    open_connection = Mock(side_effect=AssertionError("must not connect during import"))
    # reload 会重新绑定导入的符号，需在源模块替换配置读取和连接函数。
    with monkeypatch.context() as patch:
        patch.setattr(config, "get_settings", get_settings)
        patch.setattr(connection, "open_connection", open_connection)
        importlib.reload(add_update_words_service)
        importlib.reload(mcp_server)
        get_settings.assert_not_called()
        open_connection.assert_not_called()
    importlib.reload(add_update_words_service)
    importlib.reload(mcp_server)


def test_tools_are_exposed_and_save_description_explains_default(backend):
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.list_tools()
    tools = asyncio.run(run())

    assert {tool.name for tool in tools} == {"add_update_words", "count_word_usage", "count_word_miss", "reset_word_miss", "query_words", "query_users"}
    tool = next(tool for tool in tools if tool.name == "add_update_words")
    assert tool.inputSchema["required"] == ["words"]
    assert set(tool.inputSchema["properties"]) == {"words"}
    words = tool.inputSchema["properties"]["words"]
    assert words["type"] == "array" and words["minItems"] == 1
    item = words["items"]
    assert item["additionalProperties"] is False
    assert item["properties"]["action"]["default"] == "create"
    for field in ("word", "common_form", "hiragana", "meaning", "action", "tags"):
        assert item["properties"][field]["description"]
    assert all(tool.outputSchema for tool in tools)
    backend.get_settings.assert_not_called()
    backend.open_connection.assert_not_called()


@pytest.mark.parametrize("text", ["not json", "{}", "[]"])
def test_invalid_json_is_protocol_error_before_database_access(backend, text):
    result = call_add_update_words(text)
    assert result.isError is True
    backend.get_settings.assert_not_called()
    backend.open_connection.assert_not_called()


def test_tool_returns_structured_per_word_results(backend):
    backend.repository.insert.return_value = WordEntity(
        id=1, word="食べる", common_form="食べる", hiragana="たべる", meaning="吃",
        status_code="A", created_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        created_by="test-operator", updated_by="test-operator",
    )
    result = call_add_update_words([
        {"tags": ["v"], "word": "食べる", "common_form": "食べる", "hiragana": "たべる", "meaning": "吃"},
        {"tags": ["v"], "word": "飲む", "meaning": "\x00"},
    ])

    assert result.isError is False
    assert result.structuredContent == {
        "results": [
            {"index": 0, "word": "食べる", "status": "created"},
            {
                "index": 1, "word": "飲む", "status": "failed",
                "reason": "meaning 不允许包含空字符（U+0000）。",
            },
        ],
    }
    backend.get_settings.assert_called_once_with()
    backend.open_connection.assert_called_once_with(backend.settings)
    backend.repository_factory.assert_called_once_with(backend.connection)
    backend.repository.find_existing_words.assert_called_once_with(["食べる"])
    backend.repository.insert.assert_called_once_with(
        WordEntity(word="食べる", common_form="食べる", hiragana="たべる", meaning="吃"),
    )


def test_tool_serializes_optional_reason_and_missing_fields_only_when_present(backend):
    missing_fields = MissingWordFieldsError(("common_form", "hiragana"))
    backend.repository.find_existing_words.return_value = [WordEntity(word="食べる")]


    result = call_add_update_words([
        {"tags": ["v"], "word": "食べる"},
        {"tags": ["v"], "word": "飲む", "meaning": "喝"},
        {"tags": ["v"], "word": "走る", "common_form": "走る", "hiragana": "はしる", "meaning": "跑"},
    ])

    assert result.isError is False
    assert result.structuredContent == {
        "results": [
            {"index": 0, "word": "食べる", "status": "skipped", "reason": "单词已存在，未覆盖已有信息。"},
            {
                "index": 1, "word": "飲む", "status": "failed",
                "reason": str(missing_fields), "fields": ["common_form", "hiragana"],
            },
            {"index": 2, "word": "走る", "status": "created"},
        ],
    }


def test_database_connection_failure_is_protocol_error(backend):
    backend.open_connection.side_effect = DatabaseError("连接 PostgreSQL 失败，请检查配置。")
    result = call_add_update_words([{'tags': ['v'], 'word': '食べる'}])
    assert result.isError is True
    assert "连接 PostgreSQL 失败" in str(result)
    backend.repository_factory.assert_not_called()


def test_batch_lookup_failure_is_protocol_error_without_writes(backend):
    backend.repository.find_existing_words.side_effect = DatabaseError("查询单词失败，请稍后重试。")
    result = call_add_update_words([
        {"tags": ["v"], "word": "食べる", "common_form": "食べる", "hiragana": "たべる", "meaning": "吃"},
        {"tags": ["v"], "word": "飲む", "meaning": "喝", "action": "update"},
    ])

    assert result.isError is True
    assert "查询单词失败" in str(result)
    backend.repository.find_existing_words.assert_called_once_with(["食べる", "飲む"])
    backend.repository.insert.assert_not_called()


def test_surrogate_word_returns_serializable_failure_without_disrupting_valid_word(backend):
    result = call_add_update_words([
        {"tags": ["v"], "word": "\ud800"},
        {"tags": ["v"], "word": "飲む", "common_form": "飲む", "hiragana": "のむ", "meaning": "喝"},
    ])

    assert result.isError is False
    rows = result.structuredContent["results"]
    assert [row["status"] for row in rows] == ["failed", "created"]
    assert rows[0]["word"] is None
    assert rows[0]["index"] == 0
    json.dumps(result.structuredContent, ensure_ascii=False).encode("utf-8")
    backend.repository.find_existing_words.assert_called_once_with(["飲む"])
    backend.repository.insert.assert_called_once()
    assert backend.repository.insert.call_args.args[0].word == "飲む"


def test_configuration_failure_is_protocol_error(backend):
    backend.get_settings.side_effect = ValueError("缺少 THOTH_PG_DSN。")
    result = call_add_update_words([{'tags': ['v'], 'word': '食べる'}])
    assert result.isError is True
    assert "THOTH_PG_DSN" in str(result)
    backend.open_connection.assert_not_called()


def test_text_parameter_does_not_accept_array(backend):
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool_mcp("add_update_words", {"text": [{"tags": ["v"], "word": "食べる"}]})
    result = asyncio.run(run())
    assert result.isError is True
    backend.get_settings.assert_not_called()


@pytest.mark.parametrize("tags", [None, [], [""]])
def test_required_tags_failure_rejects_batch_without_config(backend, tags):
    result = call_add_update_words([{
        "word": "食べる", "tags": tags, "action": "update",
    }])
    assert result.isError is True
    backend.get_settings.assert_not_called()
    backend.repository.find_existing_words.assert_not_called()
    backend.repository.insert.assert_not_called()
    backend.repository.update.assert_not_called()
