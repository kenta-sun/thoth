"""统一注册 MCP 工具入口，各入口只转交对应 Service 执行。"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from thoth.service import save_words_service
from thoth.descriptions.save_words_descriptions import SAVE_WORDS_DESCRIPTION

# 保持协议层严格校验，拒绝将数组直接传给字符串参数 text。
mcp = FastMCP(name="thoth-words", strict_input_validation=True)


@mcp.tool(description=SAVE_WORDS_DESCRIPTION)
def save_words(text: str) -> dict[str, list[dict[str, Any]]]:
    """将单词 JSON 数组字符串交给 Service，原样返回批量处理结果。"""
    return save_words_service.save_words(text)
