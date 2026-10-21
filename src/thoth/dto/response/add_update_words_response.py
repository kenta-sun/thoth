"""单词写入响应：描述逐项业务结果和实际新增缺失的信息。"""

from typing import Literal
from pydantic import Field
from thoth.dto.response.common import OmitNoneResponse, ResponseModel


class WordWriteResult(OmitNoneResponse):
    """承载单个单词的保存状态，失败不影响其他单词。"""

    preserve_null = frozenset({"word"})
    index: int = Field(description="输入数组中的零基下标。")
    word: str | None = Field(description="单词原文；无法安全输出时为 null。")
    status: Literal["created", "updated", "skipped", "failed"] = Field(description="created 已新增，updated 已更新，skipped 已跳过，failed 保存失败。")
    reason: str | None = Field(default=None, description="跳过或失败原因；无说明时省略。")
    fields: list[Literal["common_form", "hiragana", "meaning", "tags"]] | None = Field(default=None, description="实际新增时缺少的信息字段或 tags；其他情况省略。")


class AddUpdateWordsResponse(ResponseModel):
    """按输入顺序返回写入批次的全部结果。"""

    results: list[WordWriteResult] = Field(description="每个输入单词的处理结果，顺序与输入一致。")
