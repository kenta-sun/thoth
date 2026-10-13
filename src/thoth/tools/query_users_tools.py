"""用户查询入口：将内部用户名结果映射为对外响应，不暴露表实体。"""

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from thoth.db.connection import DatabaseError
from thoth.dto.response.query_users_response import QueryUsersResponse, QueryUserResult
from thoth.service import query_users_service

QUERY_USERS_DESCRIPTION = "查询已有用户名，按用户 ID 升序返回；不创建、修改或自动选择用户。"


def query_users() -> QueryUsersResponse:
    """调用只读用户服务，将结果转换为响应，将整批错误转换为协议异常。"""
    try:
        return QueryUsersResponse(results=[QueryUserResult(username=row.username)
                                           for row in query_users_service.query_users()])
    except (ValueError, DatabaseError) as exc:
        raise ToolError(str(exc)) from exc


def register(mcp: FastMCP) -> None:
    """注册无参用户查询工具，不连接数据库。"""
    mcp.tool(description=QUERY_USERS_DESCRIPTION)(query_users)
