"""用户接口测试：真实 Mapper 查询、参数校验及 MCP 必填边界。"""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from fastmcp import Client
from thoth.db.connection import DatabaseError
from thoth.dto.word import WordWriteCommand
from thoth.dto.query_words import QueryRequest
from thoth.common.query_words import QUERY_FIELDS

from thoth.service import (add_update_words_service, query_words_service,
                          count_word_usage_service, count_word_miss_service,
                          reset_word_miss_service, query_users_service)
from thoth.service.user_lookup_service import validate_username
from thoth.mcp_server import mcp
from thoth.utils.generate_rebuild_sql import OUTPUT, render_rebuild_sql
from tests.unit.test_word_repository import ScriptedConnection

CASES = [
    (add_update_words_service, "add_update_words", [WordWriteCommand(word="a", tags=("v",))]),
    (query_words_service, "query_words", QueryRequest(QUERY_FIELDS)),
    (count_word_usage_service, "count_word_usage", []),
    (count_word_miss_service, "count_word_miss", []),
    (reset_word_miss_service, "reset_word_miss", []),
]


def install(monkeypatch, service, response):
    """仅替换连接及配置；保持用户查询、实体映射和错误转换真实执行。"""
    connection = ScriptedConnection(response)

    @contextmanager
    def connect(settings):
        """提供只含用户查询响应的连接，额外业务 SQL 会导致测试失败。"""
        yield connection

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(operator="test"))
    monkeypatch.setattr(service, "open_connection", connect)
    return connection


@pytest.mark.parametrize("service,name,text", CASES)
@pytest.mark.parametrize("username", [None, 1, True, "", " ", " a", "a\t", "\u3000a", "a" * 129, "a\x00", "\ud800"])
def test_invalid_username_fails_before_connection(monkeypatch, service, name, text, username):
    config = Mock(side_effect=AssertionError("不能读取配置"))
    monkeypatch.setattr(service, "get_settings", config)
    with pytest.raises(ValueError, match="username"):
        getattr(service, name)(text, username)
    config.assert_not_called()


@pytest.mark.parametrize("service,name,text", CASES)
def test_missing_user_blocks_all_business_sql(monkeypatch, service, name, text):
    connection = install(monkeypatch, service, None)
    with pytest.raises(ValueError, match="用户不存在"):
        getattr(service, name)(text, "未注册")
    assert len(connection.statements) == 1
    assert connection.statements[0][1] == {"username": "未注册"}
    assert connection.commits == connection.rollbacks == 0


@pytest.mark.parametrize("service,name,text", CASES)
def test_user_lookup_error_is_sanitized(monkeypatch, service, name, text):
    install(monkeypatch, service, psycopg.OperationalError("private credentials"))
    with pytest.raises(DatabaseError, match="查询用户失败") as captured:
        getattr(service, name)(text, "tester")
    assert "private" not in str(captured.value)


@pytest.mark.parametrize("username", ["中文用户", "Alice", "alice", "a b", "a" * 128])
def test_valid_username(username):
    validate_username(username)


@pytest.mark.parametrize("records", [[], [(2, "乙"), (7, "甲")]])
def test_query_users_returns_only_names(monkeypatch, records):
    connection = install(monkeypatch, query_users_service, records)
    result = query_users_service.query_users()
    assert [row.username for row in result] == [row[1] for row in records]
    assert connection.statements == [("SELECT id, username FROM user_tbl ORDER BY id", {})]


def test_query_users_error_is_sanitized(monkeypatch):
    install(monkeypatch, query_users_service, psycopg.OperationalError("private"))
    with pytest.raises(DatabaseError, match="查询用户失败") as captured:
        query_users_service.query_users()
    assert "private" not in str(captured.value)


def test_mcp_required_username_and_read_only_user_listing(monkeypatch):
    install(monkeypatch, query_users_service, [(1, "tester")])

    async def run():
        """验证协议层拒绝缺失或非字符串用户名，用户查询工具无必填参数。"""
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            for _, name, text in CASES:
                parameter = "query" if name == "query_words" else "words"
                assert set(tools[name].inputSchema["required"]) == {parameter, "username"}
                assert tools[name].inputSchema["properties"]["username"]["type"] == "string"
                assert (await client.call_tool_mcp(name, {parameter: {} if parameter == "query" else []})).isError
                assert (await client.call_tool_mcp(name, {parameter: {} if parameter == "query" else [], "username": 1})).isError
            assert not tools["query_users"].inputSchema.get("required")
            result = await client.call_tool_mcp("query_users", {})
            assert not result.isError
            assert result.structuredContent == {"results": [{"username": "tester"}]}
    asyncio.run(run())


def test_combined_sql_matches_sources():
    assert OUTPUT.read_text() == render_rebuild_sql()
