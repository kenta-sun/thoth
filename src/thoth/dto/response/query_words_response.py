"""查询响应：使用已设置字段记录投影，保留被选择字段中的合法 null。"""

from pydantic import Field, model_serializer
from thoth.dto.response.common import ResponseModel


class QueryWordResult(ResponseModel):
    """承载一个单词的投影结果；未选择的字段不输出。"""

    word: str | None = Field(default=None, description="单词原文，仅选择该字段时输出。")
    common_form: str | None = Field(default=None, description="常见写法，仅选择该字段时输出。")
    hiragana: str | None = Field(default=None, description="平假名读音，仅选择该字段时输出。")
    meaning: str | None = Field(default=None, description="中文释义，仅选择该字段时输出。")
    tags: list[str] | None = Field(default=None, description="按编码排序的标签集合，仅选择该字段时输出。")
    usage_count: int | None = Field(default=None, description="指定用户使用次数，无统计按零，仅选择该字段时输出。")
    miss_count: int | None = Field(default=None, description="指定用户陌生次数，无统计按零，仅选择该字段时输出。")

    @model_serializer(mode="wrap")
    def serialize_projection(self, handler):
        """按字段是否被赋值输出，不能用排除 None 的方式丢弃选中字段。"""
        return {name: value for name, value in handler(self).items() if name in self.model_fields_set}


class QueryWordsResponse(ResponseModel):
    """承载只包含请求投影字段的查询结果。"""

    results: list[QueryWordResult] = Field(description="查询匹配的单词列表；无匹配时为空数组。")
