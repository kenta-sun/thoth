"""SQL 构建工具：依据已校验请求和可信 Mapper 配置生成模板与参数，不访问数据库。"""

from thoth.dto.query_words import BuiltQuery, QueryRequest, QuerySqlSpec

# 仅允许固定操作符参与语句结构，业务值一律绑定参数。
_OPERATORS = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "like": "LIKE"}


def build_query(request: QueryRequest, spec: QuerySqlSpec) -> BuiltQuery:
    """将已校验的查询请求转换为 SQL 模板和独立绑定参数，不访问数据库。

    先收集返回、筛选和排序涉及的字段，按 Mapper 配置确定关联表；
    再依次组装 SELECT、FROM、JOIN、WHERE、ORDER BY 和可选的 LIMIT。
    SQL 结构来自可信配置及固定操作符，用户提供的条件值只进入参数字典。

    Args:
        request: Service 已完成值类型和协议校验的请求。fields 指定返回字段
            及顺序；conditions 为空时只保留固定筛选条件，否则全部以 AND
            连接；sort 为空时只使用固定末级排序；limit 为 None 时不限数量。
        spec: Mapper 提供的可信 SQL 配置，定义字段表达式、关联依赖、固定
            筛选和末级排序，不能由请求或外部 JSON 构造。

    Returns:
        BuiltQuery 对象，其中 sql 含 psycopg 命名占位符，params 保存对应
        的绑定值；由 Mapper 交给 cursor.execute 执行，不修改请求或配置。

    Raises:
        ValueError: 字段、操作或排序不符合白名单，或投影、limit 无效。
    """
    # 1. 收集本次查询用到的全部字段；仅用于筛选或排序的字段也可能依赖关联表。
    # 集合用于去重；这里的 <= 表示子集判断，确保每个字段都在 Mapper 白名单中。
    if not request.fields:
        raise ValueError("fields 不能为空。")
    referenced = set(request.fields)
    referenced.update(condition.field for condition in request.conditions)
    referenced.update(name for name, _ in request.sort)
    if not referenced <= spec.fields.keys():
        raise ValueError("查询包含不支持的字段。")
    # 2. 汇总各字段声明的关联依赖，同一个关联只添加一次。
    # 例如 usage_count 的返回、筛选或排序都会触发它所依赖的统计表关联。
    required_joins = {join for name in referenced for join in spec.fields[name].joins}
    # SELECT 仍按 request.fields 的顺序生成；AS 将数据库表达式命名为业务字段，
    # 便于 Mapper 按列名映射结果。表达式来自可信配置，别名已通过字段白名单校验。
    selected = ", ".join(f'{spec.fields[name].expression} AS "{name}"' for name in request.fields)
    parts = [f"SELECT {selected}", f"FROM {spec.source}"]
    # 按配置中的顺序输出所需 JOIN，避免依赖集合的无序遍历影响 SQL 生成顺序。
    parts.extend(fragment for name, fragment in spec.joins.items() if name in required_joins)
    # 3. WHERE 先保留 Mapper 的固定约束（如排除已删除记录），请求不能覆盖它。
    # conditions 保存 SQL 条件片段，params 独立保存用户值，两者不做字符串插值。
    conditions = [spec.predicate]
    params: dict[str, object] = {}
    for index, condition in enumerate(request.conditions):
        definition = spec.fields[condition.field]
        if condition.operator not in definition.operators:
            raise ValueError("查询包含不支持的操作。")
        # 每个条件分配独立参数名；同一字段的上下界条件也不会互相覆盖。
        # 例如 p0 对应 %(p0)s，占位符留给 psycopg 绑定，不在这里替换成实际值。
        key = f"p{index}"
        placeholder = f"%({key})s"
        if condition.operator == "in" and definition.membership_expression is not None:
            # 标签使用 Mapper 配置的 EXISTS 相关子查询，判断是否命中任一标签，
            # 避免一词多标签扩大结果行数；只替换模板占位标记，不插入用户值。
            conditions.append(definition.membership_expression.replace("{value}", placeholder))
        elif condition.operator == "in":
            # 普通字段的 in 转为 PostgreSQL 的 = ANY(数组参数)，
            # 表示等于数组中的任意一个值，无需按数组长度拼接占位符。
            conditions.append(f"{definition.expression} = ANY({placeholder})")
        else:
            # eq、gte 等协议操作名映射为固定 SQL 运算符；字段表达式仍取自配置。
            conditions.append(f"{definition.expression} {_OPERATORS[condition.operator]} {placeholder}")
        # 解析层将 in 的值存为元组；此处转为列表，让 psycopg 按 PostgreSQL
        # 数组绑定给 ANY。其他操作直接保留已校验的单值。
        params[key] = list(condition.value) if condition.operator == "in" else condition.value
    # 每个条件单独加括号，保留配置表达式内部的逻辑分组，再要求所有条件同时满足。
    parts.append("WHERE " + " AND ".join(f"({item})" for item in conditions))
    # 4. 按请求顺序确定排序优先级；字段需允许排序，方向只能为 asc 或 desc。
    ordering = []
    for name, direction in request.sort:
        if not spec.fields[name].sortable or direction not in {"asc", "desc"}:
            raise ValueError("查询包含不支持的排序。")
        ordering.append(f"{spec.fields[name].expression} {direction.upper()}")
    # 末尾补固定排序（如主键升序），使前面排序值相同的记录仍有确定的顺序；
    # 未指定 sort 时，也依靠这个末级排序生成 ORDER BY。
    parts.append("ORDER BY " + ", ".join([*ordering, spec.tie_breaker]))
    # 5. 仅在指定数量时添加 LIMIT，数量同样使用参数绑定。
    # 精确检查 int 类型，是因为 Python 的 bool 也是 int 子类，但不是合法数量。
    if request.limit is not None:
        if type(request.limit) is not int or request.limit <= 0:
            raise ValueError("limit 必须为正整数。")
        parts.append("LIMIT %(limit)s")
        params["limit"] = request.limit
    # 按 SQL 子句顺序合并模板，与参数一起交回 Mapper；构建过程不执行查询。
    return BuiltQuery("\n".join(parts), params)
