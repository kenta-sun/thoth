"""count_word_usage 工具入口：接收结构化单词列表，调用业务服务并转换结果与异常。"""

from typing import Annotated
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from thoth.db.connection import DatabaseError
from thoth.dto.request.common import Username
from thoth.dto.response.count_word_usage_response import CountWordUsageResponse
from thoth.service import count_word_usage_service
from thoth.tools.word_stats_mapping import to_stats_results

COUNT_WORD_USAGE_DESCRIPTION = """为指定用户的已有未删除单词增加一次使用计数。
单词按原文精确匹配；无效文本、重复项及不存在的单词跳过，按输入顺序返回结果。
计数不是幂等操作，失败时不要自动重试；初始化与加一独立提交，加一失败可能保留零值记录。
用户名必须已存在，可先调用 query_users 查询。"""


def count_word_usage(
    username: Username,
    words: Annotated[list[str], Field(description="需要处理的单词原文列表，允许空数组；重复单词仅处理第一次，其余项返回跳过。")],
) -> CountWordUsageResponse:
    """将单词列表交给专属 Service，转换业务结果；整批业务异常转为 MCP 工具错误。"""
    try:
        rows = count_word_usage_service.count_word_usage(words, username)
        return CountWordUsageResponse(results=to_stats_results(rows))
    except (ValueError, DatabaseError) as exc:
        raise ToolError(str(exc)) from exc


def register(mcp: FastMCP) -> None:
    """在统一服务器注册本工具，不读取配置或连接数据库。"""
    mcp.tool(description=COUNT_WORD_USAGE_DESCRIPTION)(count_word_usage)
