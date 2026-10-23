"""单词查询入口：转换类型化条件为内部查询 DTO，再按投影构造响应。"""

from typing import Annotated
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from thoth.db.connection import DatabaseError
from thoth.dto.request.common import Username
from thoth.dto.request.query_words_request import WordQueryInput
from thoth.dto.response.query_words_response import QueryWordsResponse, QueryWordResult
from thoth.dto.query_words import QueryCondition, QueryRequest, QueryWordResult as InternalQueryWordResult
from thoth.service import query_words_service

QUERY_WORDS_DESCRIPTION = """查询未删除的日语单词，不修改数据。
使用次数和陌生次数按指定用户隔离，无统计记录按零参与筛选、排序和返回。
各字段及同字段多个操作均为 AND；筛选和排序字段不必出现在返回字段中。
省略 sort 不指定结果顺序；显式 field=random 随机排序，可省略 direction，排序后再限量。
只返回选中的业务字段，无匹配返回空数组。
用户名必须已存在，可先调用 query_users 查询。"""


def to_query_request(query: WordQueryInput) -> QueryRequest:
    """将已校验的字段条件展开为内部操作列表，不向业务层传递接口子模型。"""
    conditions = []
    # dump 仅在入口用于遍历动态出现的字段，随后立即转换为固定内部 DTO。
    for name, operations in query.where.model_dump(by_alias=True, exclude_unset=True).items():
        for operator, value in operations.items():
            conditions.append(QueryCondition(name, operator, tuple(value) if operator == "in" else value))
    return QueryRequest(
        fields=tuple(query.fields), conditions=tuple(conditions),
        sort=tuple((item.field, item.direction) for item in query.sort), limit=query.limit,
    )


def to_query_response(rows: list[InternalQueryWordResult], fields: tuple[str, ...]) -> QueryWordsResponse:
    """只设置被投影的响应字段，选中字段的合法 null 仍显式输出。"""
    results = []
    for row in rows:
        values = {}
        for name in fields:
            if name == "tags":
                value = [tag.tag_code for tag in row.tags]
            elif name == "usage_count":
                value = row.usage.usage_count
            elif name == "miss_count":
                value = row.miss.miss_count
            else:
                value = getattr(row.word, name)
            values[name] = value
        results.append(QueryWordResult(**values))
    return QueryWordsResponse(results=results)


def query_words(
    username: Username,
    query: Annotated[WordQueryInput, Field(description="筛选、投影、排序及限量；空对象查询全部未删除单词。")],
) -> QueryWordsResponse:
    """将结构化查询适配为业务请求，投影业务结果并转换整批异常。"""
    try:
        request = to_query_request(query)
        return to_query_response(query_words_service.query_words(request, username), request.fields)
    except (ValueError, DatabaseError) as exc:
        raise ToolError(str(exc)) from exc


def register(mcp: FastMCP) -> None:
    """注册查询工具，不读取配置或连接数据库。"""
    mcp.tool(description=QUERY_WORDS_DESCRIPTION)(query_words)
