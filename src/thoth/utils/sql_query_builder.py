"""SQL 构建工具：依据已校验请求和可信 Mapper 配置生成模板与参数，不访问数据库。"""

from thoth.dto.query_words import BuiltQuery, QueryRequest, QuerySqlSpec

# 仅允许固定操作符参与语句结构，业务值一律绑定参数。
_OPERATORS = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "like": "LIKE"}


def build_query(request: QueryRequest, spec: QuerySqlSpec) -> BuiltQuery:
    """构建筛选、投影、排序和限量 SQL，并独立返回驱动参数。

    Args:
        request: Service 校验后的查询请求；limit 为 None 时不添加 LIMIT。
        spec: Mapper 提供的可信 SQL 配置，不能由请求或外部 JSON 构造。

    Returns:
        可以直接交给 cursor.execute 的模板及参数，不修改请求或配置。

    Raises:
        ValueError: 字段、操作或排序不符合白名单，或投影、limit 无效。
    """
    if not request.fields:
        raise ValueError("fields 不能为空。")
    referenced = set(request.fields)
    referenced.update(condition.field for condition in request.conditions)
    referenced.update(name for name, _ in request.sort)
    if not referenced <= spec.fields.keys():
        raise ValueError("查询包含不支持的字段。")
    required_joins = {join for name in referenced for join in spec.fields[name].joins}
    selected = ", ".join(f'{spec.fields[name].expression} AS "{name}"' for name in request.fields)
    parts = [f"SELECT {selected}", f"FROM {spec.source}"]
    parts.extend(fragment for name, fragment in spec.joins.items() if name in required_joins)
    conditions = [spec.predicate]
    params: dict[str, object] = {}
    for index, condition in enumerate(request.conditions):
        definition = spec.fields[condition.field]
        if condition.operator not in definition.operators:
            raise ValueError("查询包含不支持的操作。")
        key = f"p{index}"
        placeholder = f"%({key})s"
        if condition.operator == "in" and definition.membership_expression is not None:
            # 标签表达式由 Mapper 配置为相关子查询，避免一词多标签扩大结果行数。
            conditions.append(definition.membership_expression.replace("{value}", placeholder))
        elif condition.operator == "in":
            conditions.append(f"{definition.expression} = ANY({placeholder})")
        else:
            conditions.append(f"{definition.expression} {_OPERATORS[condition.operator]} {placeholder}")
        params[key] = list(condition.value) if condition.operator == "in" else condition.value
    parts.append("WHERE " + " AND ".join(f"({item})" for item in conditions))
    ordering = []
    for name, direction in request.sort:
        if not spec.fields[name].sortable or direction not in {"asc", "desc"}:
            raise ValueError("查询包含不支持的排序。")
        ordering.append(f"{spec.fields[name].expression} {direction.upper()}")
    parts.append("ORDER BY " + ", ".join([*ordering, spec.tie_breaker]))
    if request.limit is not None:
        if type(request.limit) is not int or request.limit <= 0:
            raise ValueError("limit 必须为正整数。")
        parts.append("LIMIT %(limit)s")
        params["limit"] = request.limit
    return BuiltQuery("\n".join(parts), params)
