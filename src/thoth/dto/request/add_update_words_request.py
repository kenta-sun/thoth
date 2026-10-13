"""单词写入请求：描述单项字段，新增完整性和数据库约束由业务层处理。"""

from typing import Annotated, Literal
from pydantic import Field
from thoth.common.tags import TAG_OPTIONS_DESCRIPTION
from thoth.dto.request.common import RequestModel

TagCode = Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{1,32}$", description="已有标签编码，1～32 位英文字母、数字或下划线。")]


class WordWriteInput(RequestModel):
    """承载一个单词的写入信息与操作，不承载数据库记录。"""

    word: str = Field(description="单词原文，精确匹配；必须非空，业务层逐项检查文本可写入性。")
    common_form: str | None = Field(default=None, description="常见写法；新增时须有有效值，更新时省略、null 或空白均保留原值。")
    hiragana: str | None = Field(default=None, description="平假名读音；新增时须有有效值，更新时省略、null 或空白均保留原值。")
    meaning: str | None = Field(default=None, description="中文释义；新增时须有有效值，更新时省略、null 或空白均保留原值。")
    tags: list[TagCode] = Field(min_length=1, description="完整的新标签集合，重复编码去重；更新时替换全部旧标签，不允许清空。" + TAG_OPTIONS_DESCRIPTION)
    action: Literal["create", "update"] = Field(default="create", description="create：不存在则新增，已存在则跳过；update：不存在则新增，已存在则局部更新。")
