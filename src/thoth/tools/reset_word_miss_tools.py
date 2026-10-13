"""reset_word_miss 工具入口：接收结构化单词列表，调用业务服务并转换结果与异常。"""

from typing import Annotated
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from thoth.db.connection import DatabaseError
from thoth.dto.request.common import Username
from thoth.dto.response.reset_word_miss_response import ResetWordMissResponse
from thoth.service import reset_word_miss_service
from thoth.tools.word_stats_mapping import to_stats_results

RESET_WORD_MISS_DESCRIPTION = """清零指定用户的已有陌生计数，不创建统计记录，不改变使用次数。
单词按原文精确匹配；无效文本、重复项及不存在的单词跳过，按输入顺序返回结果。
每个单词独立事务；无统计记录或已经为零时跳过，不修改审计信息。
用户名必须已存在，可先调用 query_users 查询。"""


def reset_word_miss(
    username: Username,
    words: Annotated[list[str], Field(description="需要处理的单词原文列表，允许空数组；重复单词仅处理第一次，其余项返回跳过。")],
) -> ResetWordMissResponse:
    """将单词列表交给专属 Service，转换业务结果；整批业务异常转为 MCP 工具错误。"""
    try:
        rows = reset_word_miss_service.reset_word_miss(words, username)
        return ResetWordMissResponse(results=to_stats_results(rows))
    except (ValueError, DatabaseError) as exc:
        raise ToolError(str(exc)) from exc


def register(mcp: FastMCP) -> None:
    """在统一服务器注册本工具，不读取配置或连接数据库。"""
    mcp.tool(description=RESET_WORD_MISS_DESCRIPTION)(reset_word_miss)
