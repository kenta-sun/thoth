"""MCP 工具入口层：注册工具及对外说明，将调用转交对应 Service 并返回结果。"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from thoth.service import add_update_words_service, count_word_usage_service, count_word_miss_service, reset_word_miss_service
from thoth.descriptions.count_word_usage_descriptions import COUNT_WORD_USAGE_DESCRIPTION
from thoth.descriptions.count_word_miss_descriptions import COUNT_WORD_MISS_DESCRIPTION
from thoth.descriptions.reset_word_miss_descriptions import RESET_WORD_MISS_DESCRIPTION
from thoth.descriptions.add_update_words_descriptions import ADD_UPDATE_WORDS_DESCRIPTION
from thoth.descriptions.query_words_descriptions import QUERY_WORDS_DESCRIPTION
from thoth.service import query_words_service, query_users_service
from thoth.descriptions.query_users_descriptions import QUERY_USERS_DESCRIPTION

# 启用严格参数校验，拒绝将数组直接传给字符串参数 text。
mcp = FastMCP(name="thoth-words", strict_input_validation=True)


@mcp.tool(description=QUERY_WORDS_DESCRIPTION)
def query_words(text: str, username: str) -> dict[str, list[dict[str, Any]]]:
    """将 username 和查询 JSON 字符串交给专属 Service，返回只含选定字段的单词列表。"""
    return query_words_service.query_words(text, username)


@mcp.tool(description=ADD_UPDATE_WORDS_DESCRIPTION)
def add_update_words(text: str, username: str) -> dict[str, list[dict[str, Any]]]:
    """将 username 和单词 JSON 数组字符串交给 Service，返回逐项结果；ToolError 由框架转为工具错误。"""
    return add_update_words_service.add_update_words(text, username)


@mcp.tool(description=COUNT_WORD_USAGE_DESCRIPTION)
def count_word_usage(text: str, username: str) -> dict[str, list[dict[str, Any]]]:
    """将 username 和单词字符串数组交给使用计数 Service，返回逐项结果。"""
    return count_word_usage_service.count_word_usage(text, username)


@mcp.tool(description=COUNT_WORD_MISS_DESCRIPTION)
def count_word_miss(text: str, username: str) -> dict[str, list[dict[str, Any]]]:
    """将 username 和单词字符串数组交给错误计数 Service，返回逐项结果。"""
    return count_word_miss_service.count_word_miss(text, username)


@mcp.tool(description=RESET_WORD_MISS_DESCRIPTION)
def reset_word_miss(text: str, username: str) -> dict[str, list[dict[str, Any]]]:
    """将 username 和清零 JSON 数组字符串交给专属 Service，返回逐项结果。"""
    return reset_word_miss_service.reset_word_miss(text, username)


@mcp.tool(description=QUERY_USERS_DESCRIPTION)
def query_users() -> dict[str, list[dict[str, str]]]:
    """返回按用户 ID 排序的已有用户名，不提供用户写入能力。"""
    return query_users_service.query_users()
