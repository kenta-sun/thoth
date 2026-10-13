"""MCP 工具注册层：统一组织独立入口模块，不创建服务器或访问数据库。"""

from fastmcp import FastMCP
from thoth.tools import (
    add_update_words_tools, count_word_usage_tools, count_word_miss_tools,
    reset_word_miss_tools, query_words_tools, query_users_tools,
)


def register_tools(mcp: FastMCP) -> None:
    """将六个独立工具注册到调用方提供的同一个服务器实例。"""
    for module in (
        add_update_words_tools, count_word_usage_tools, count_word_miss_tools,
        reset_word_miss_tools, query_words_tools, query_users_tools,
    ):
        module.register(mcp)
