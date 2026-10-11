"""MCP 工具入口层：注册工具及对外说明，将调用转交对应 Service 并返回结果。"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from thoth.service import save_words_service
from thoth.descriptions.save_words_descriptions import SAVE_WORDS_DESCRIPTION

# 启用严格参数校验，拒绝将数组直接传给字符串参数 text。
mcp = FastMCP(name="thoth-words", strict_input_validation=True)


@mcp.tool(description=SAVE_WORDS_DESCRIPTION)
def save_words(text: str) -> dict[str, list[dict[str, Any]]]:
    """将单词 JSON 数组字符串交给 Service，返回逐项结果；ToolError 由框架转为工具错误。"""
    return save_words_service.save_words(text)
