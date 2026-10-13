"""查询请求模型：以字段条件和排序对象描述查询，在进入业务层前校验结构。"""

from typing import Annotated, Literal, Any
from pydantic import AfterValidator, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema
from thoth.common.query_words import QUERY_FIELDS
from thoth.common.tags import TAG_OPTIONS_DESCRIPTION
from thoth.dto.request.common import RequestModel


def _database_text(value: str) -> str:
    """校验查询文本可编码且无空字符，保留空字符串、空白和 LIKE 模式原文。"""
    if "\x00" in value:
        raise ValueError("查询文本不能包含空字符。")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("查询文本必须能编码为 UTF-8。") from None
    return value


QueryText = Annotated[str, AfterValidator(_database_text)]
CountValue = Annotated[int, Field(ge=0, le=9223372036854775807, strict=True)]
QueryField = Literal["word", "common_form", "hiragana", "meaning", "tags", "usage_count", "miss_count"]
SortField = Literal["word", "common_form", "hiragana", "meaning", "usage_count", "miss_count"]


def _query_schema(schema: dict[str, Any]) -> None:
    """省略值仅是内部标记，移除非 nullable 字段上的 null 默认值。"""
    for definition in schema.get("properties", {}).values():
        if definition.get("default", object()) is None:
            definition.pop("default")


def _condition_schema(schema: dict[str, Any]) -> None:
    """在条件 Schema 中声明至少一个操作，同时清理内部省略标记。"""
    _query_schema(schema)
    schema["minProperties"] = 1


class QueryModel(RequestModel):
    """查询对象允许省略可选字段，但不允许显式 null；内部 None 仅代表省略。"""

    model_config = ConfigDict(json_schema_extra=_query_schema)

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        """在默认值填充前拒绝显式 null，使运行时规则与非 nullable Schema 一致。"""
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("查询字段不能显式传入 null。")
        return value


class ConditionInput(QueryModel):
    """条件对象至少包含一个操作，多个操作按 AND 组合。"""

    model_config = ConfigDict(json_schema_extra=_condition_schema)

    @model_validator(mode="after")
    def require_operation(self):
        """拒绝空条件对象；字段是否出现由框架记录，不根据默认值推断。"""
        if not self.model_fields_set:
            raise ValueError("字段条件不能为空。")
        return self


class TextCondition(ConditionInput):
    """普通文本的相等或集合查询条件。"""

    eq: QueryText | SkipJsonSchema[None] = Field(default=None, description="精确相等，保留空字符串和原始空白。")
    in_: list[QueryText] | SkipJsonSchema[None] = Field(default=None, alias="in", min_length=1, description="匹配非空数组中的任一文本。")


class CommonFormCondition(TextCondition):
    """常见写法额外支持 PostgreSQL LIKE 模式。"""

    like: QueryText | SkipJsonSchema[None] = Field(default=None, description="LIKE 模式：% 匹配任意长度，_ 匹配单字符，反斜杠转义；不自动添加通配符。")


class CountCondition(ConditionInput):
    """非负 BIGINT 计数的比较条件，无统计记录按零参与查询。"""

    eq: CountValue | SkipJsonSchema[None] = Field(default=None, description="计数等于此值。")
    in_: list[CountValue] | SkipJsonSchema[None] = Field(default=None, alias="in", min_length=1, description="计数匹配非空数组中的任一值。")
    gt: CountValue | SkipJsonSchema[None] = Field(default=None, description="计数大于此值。")
    gte: CountValue | SkipJsonSchema[None] = Field(default=None, description="计数大于或等于此值。")
    lt: CountValue | SkipJsonSchema[None] = Field(default=None, description="计数小于此值。")
    lte: CountValue | SkipJsonSchema[None] = Field(default=None, description="计数小于或等于此值。")


class TagCondition(ConditionInput):
    """按任一标签编码匹配，不推断父子标签。"""

    in_: list[QueryText] = Field(alias="in", min_length=1, description="匹配拥有任一编码的单词，不推断标签层级。" + TAG_OPTIONS_DESCRIPTION)


class WordWhereInput(QueryModel):
    """所有已提供字段条件同时满足；空对象不增加筛选。"""

    word: TextCondition | SkipJsonSchema[None] = Field(default=None, description="按单词原文筛选。")
    common_form: CommonFormCondition | SkipJsonSchema[None] = Field(default=None, description="按常见写法筛选，支持 LIKE。")
    hiragana: TextCondition | SkipJsonSchema[None] = Field(default=None, description="按平假名读音筛选。")
    meaning: TextCondition | SkipJsonSchema[None] = Field(default=None, description="按中文释义筛选。")
    tags: TagCondition | SkipJsonSchema[None] = Field(default=None, description="按已有标签编码筛选。")
    usage_count: CountCondition | SkipJsonSchema[None] = Field(default=None, description="指定用户的使用次数，无统计按零。")
    miss_count: CountCondition | SkipJsonSchema[None] = Field(default=None, description="指定用户的陌生次数，无统计按零。")


class WordSortInput(QueryModel):
    """指定一个排序字段与方向；列表顺序代表排序优先级。"""

    field: SortField = Field(description="排序业务字段，不支持标签数组排序。")
    direction: Literal["asc", "desc"] = Field(description="asc 升序，desc 降序；同值最终按单词 ID 升序。")


class WordQueryInput(QueryModel):
    """承载完整查询条件，空对象查询全部未删除单词。"""

    where: WordWhereInput = Field(default_factory=WordWhereInput, description="同时满足的筛选条件；省略或空对象不增加筛选。")
    fields: list[QueryField] = Field(default_factory=lambda: list(QUERY_FIELDS), min_length=1, description="返回字段，省略则返回全部业务字段；不允许重复。")
    sort: list[WordSortInput] = Field(default_factory=list, min_length=1, description="按优先级排序；省略时按单词 ID 升序，显式数组不得为空或重复字段。")
    limit: Annotated[int, Field(ge=1, le=9223372036854775807, strict=True)] | SkipJsonSchema[None] = Field(default=None, description="最大返回条数，省略时不限数量。")

    @model_validator(mode="after")
    def unique_fields(self):
        """拒绝重复投影或重复排序，避免查询含义不明确。"""
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("fields 不允许重复字段。")
        names = [item.field for item in self.sort]
        if len(names) != len(set(names)):
            raise ValueError("sort 不允许重复排序字段。")
        return self
