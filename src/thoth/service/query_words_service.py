"""query_words 专属服务：解析查询 JSON、校验能力、调用 Mapper 并序列化投影结果。"""

import json
from typing import Any

import psycopg
from fastmcp.exceptions import ToolError

from thoth.common.config import get_settings
from thoth.common.query_words import COUNT_FIELDS, QUERY_FIELDS, QUERY_OPERATORS
from thoth.dao.word_tbl_mapper import WordTblMapper
from thoth.db.connection import DatabaseError, open_connection
from thoth.dto.query_words import QueryCondition, QueryRequest, QueryWordResult
from thoth.utils.json_utils import reject_json_constant, unique_json_object


def _validate_value(value: Any, name: str, path: str) -> None:
    """校验单值类型与数据库文本可编码性，保留空字符串和原始空白。"""
    if name in COUNT_FIELDS:
        if type(value) is not int or not 0 <= value <= 9223372036854775807:
            raise ValueError(f"{path} 必须是 BIGINT 范围内的非负整数。")
    else:
        if not isinstance(value, str):
            raise ValueError(f"{path} 必须是字符串。")
        if "\x00" in value:
            raise ValueError(f"{path} 不能包含空字符。")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError(f"{path} 必须能编码为 UTF-8。") from None


def _parse_conditions(where: Any) -> tuple[QueryCondition, ...]:
    """展开 where 为同时满足的条件列表；空对象表示无额外筛选。"""
    if not isinstance(where, dict):
        raise ValueError("where 必须是对象。")
    conditions = []
    for name, raw in where.items():
        if name not in QUERY_OPERATORS:
            raise ValueError(f"where.{name} 是不支持的字段。")
        operations = raw if isinstance(raw, dict) else {"eq": raw}
        if not operations:
            raise ValueError(f"where.{name} 条件不能为空。")
        for operator, value in operations.items():
            path = f"where.{name}.{operator}"
            # 相等只能使用直接值，避免同一语义出现两套对外写法。
            if operator not in QUERY_OPERATORS[name] or (isinstance(raw, dict) and operator == "eq"):
                raise ValueError(f"{path} 是不支持的操作。")
            if operator == "in":
                if not isinstance(value, list) or not value:
                    raise ValueError(f"{path} 必须是非空数组。")
                for index, item in enumerate(value):
                    _validate_value(item, name, f"{path}[{index}]")
                value = tuple(value)
            else:
                _validate_value(value, name, path)
            conditions.append(QueryCondition(name, operator, value))
    return tuple(conditions)


def parse_query(text: str) -> QueryRequest:
    """将严格 JSON 对象解析为查询 DTO，不读取配置或访问数据库。

    Args:
        text: JSON 对象字符串；空对象表示查询所有未删除单词的全部业务字段。

    Returns:
        已校验的筛选、投影、排序和限量请求。

    Raises:
        ValueError: JSON、字段或条件不符合查询协议，消息包含错误位置。
    """
    if not isinstance(text, str):
        raise ValueError("text 必须是 JSON 对象字符串。")
    try:
        raw = json.loads(text, object_pairs_hook=unique_json_object, parse_constant=reject_json_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"text 不是合法 JSON：第 {exc.lineno} 行、第 {exc.colno} 列格式错误。") from None
    except RecursionError:
        raise ValueError("JSON 嵌套层级过深。") from None
    if not isinstance(raw, dict):
        raise ValueError("text 必须包含 JSON 对象。")
    if raw.keys() - {"where", "fields", "sort", "limit"}:
        raise ValueError("只支持 where、fields、sort、limit 四个顶层字段。")
    fields = raw.get("fields", list(QUERY_FIELDS))
    if not isinstance(fields, list) or not fields:
        raise ValueError("fields 必须是非空字段数组。")
    if any(not isinstance(name, str) or name not in QUERY_FIELDS for name in fields):
        raise ValueError("fields 包含不支持的字段。")
    if len(set(fields)) != len(fields):
        raise ValueError("fields 不允许重复字段。")
    sorting = raw.get("sort", [])
    if not isinstance(sorting, list) or ("sort" in raw and not sorting):
        raise ValueError("sort 必须是非空排序数组。")
    seen = set()
    for index, item in enumerate(sorting):
        if (not isinstance(item, list) or len(item) != 2
                or not isinstance(item[0], str) or item[0] not in QUERY_FIELDS
                or item[0] == "tags" or item[1] not in ("asc", "desc")):
            raise ValueError(f"sort[{index}] 必须为 [可排序字段, asc或desc]。")
        if item[0] in seen:
            raise ValueError(f"sort[{index}] 重复指定排序字段。")
        seen.add(item[0])
    limit = raw.get("limit")
    if "limit" in raw and (type(limit) is not int or not 1 <= limit <= 9223372036854775807):
        raise ValueError("limit 必须为 BIGINT 范围内的正整数。")
    return QueryRequest(tuple(fields), _parse_conditions(raw.get("where", {})),
                        tuple(tuple(item) for item in sorting), limit)


def serialize_query(rows: list[QueryWordResult], fields: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    """按投影输出对象列表，未选字段不输出；空结果保持 results 为空数组。"""
    results = []
    for row in rows:
        result = {}
        for name in fields:
            if name == "tags":
                value = [tag.tag_code for tag in row.tags]
            elif name == "usage_count":
                value = row.usage.usage_count
            elif name == "miss_count":
                value = row.miss.miss_count
            else:
                value = getattr(row.word, name)
            result[name] = value
        results.append(result)
    return {"results": results}


def query_words(text: str) -> dict[str, list[dict[str, Any]]]:
    """查询未删除单词，缺失统计按零参与筛选和排序；不产生任何数据库写入。

    Args:
        text: JSON 对象字符串，省略 limit 时返回全部匹配记录。

    Returns:
        仅包含请求投影字段的 results 数组。

    Raises:
        ToolError: 输入、配置、连接或查询失败；驱动错误不暴露 SQL 与连接详情。
    """
    try:
        request = parse_query(text)
        with open_connection(get_settings()) as connection:
            rows = WordTblMapper(connection).query_words(request)
        return serialize_query(rows, request.fields)
    except (ValueError, DatabaseError) as exc:
        raise ToolError(str(exc)) from exc
    except psycopg.Error as exc:
        code = f"（SQLSTATE {exc.sqlstate}）" if exc.sqlstate else ""
        raise ToolError(f"查询单词失败{code}。") from exc
