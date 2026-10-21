"""单词写入请求：描述单项字段，新增完整性和数据库约束由业务层处理。"""

from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema
from thoth.common.tags import TAG_OPTIONS_DESCRIPTION
from thoth.dto.request.common import RequestModel

TagCode = Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{1,32}$", description="已有标签编码，1～32 位英文字母、数字或下划线。")]


class WordWriteInput(RequestModel):
    """承载一个单词的写入信息与操作，不承载数据库记录。"""

    word: str = Field(description="单词原文，精确匹配；必须非空，业务层逐项检查文本可写入性。")
    common_form: str | None = Field(default=None, description="常见写法；新增时须有有效值，更新时省略、null 或空白均保留原值。")
    hiragana: str | None = Field(default=None, description="平假名读音；新增时须有有效值，更新时省略、null 或空白均保留原值。")
    meaning: str | None = Field(default=None, description="中文释义；新增时须有有效值，更新时省略、null 或空白均保留原值。")
    tags: Annotated[list[TagCode], Field(min_length=1)] | SkipJsonSchema[None] = Field(default=None, description="create 必填；update 时省略则保留原标签，转为新增时仍必填。提供时为完整的新标签集合，重复编码去重并替换全部旧标签；不接受 null 或空数组。" + TAG_OPTIONS_DESCRIPTION)
    action: Literal["create", "update"] = Field(default="create", description="create：不存在则新增，已存在则跳过；update：不存在则新增，已存在则局部更新。")

    @field_validator("tags")
    @classmethod
    def validate_supplied_tags(cls, value: list[str] | None) -> list[str]:
        """显式提供标签时拒绝 null；省略字段的默认 None 不参与字段校验。"""
        if value is None:
            raise ValueError("tags 不接受 null；更新时不修改标签请省略该字段。")
        return value

    @model_validator(mode="after")
    def validate_create_tags(self) -> "WordWriteInput":
        """create 必须提供标签；update 的新增完整性由业务层根据存在性检查。"""
        if self.action == "create" and self.tags is None:
            raise ValueError("create 必须提供非空 tags。")
        return self
