"""公共查询定义：集中声明业务字段及操作能力，供 Service 校验和 Mapper 配置使用。"""

from types import MappingProxyType

# 查询接口的固定业务字段；审计字段不在开放范围内。
TEXT_FIELDS = ("word", "common_form", "hiragana", "meaning")
COUNT_FIELDS = ("usage_count", "miss_count")
QUERY_FIELDS = (*TEXT_FIELDS, "tags", *COUNT_FIELDS)
QUERY_OPERATORS = MappingProxyType({
    **{name: frozenset({"eq", "in"}) for name in TEXT_FIELDS},
    "common_form": frozenset({"eq", "in", "like"}),
    "tags": frozenset({"in"}),
    **{name: frozenset({"eq", "in", "gt", "gte", "lt", "lte"}) for name in COUNT_FIELDS},
})
