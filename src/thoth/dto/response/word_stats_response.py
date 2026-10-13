"""统计响应子模型：三个统计工具共用逐项状态和计数结构。"""

from typing import Literal
from pydantic import Field
from thoth.dto.response.common import OmitNoneResponse


class WordCounts(OmitNoneResponse):
    """仅包含本次操作实际取得的计数；零值仍输出。"""

    usage_count: int | None = Field(default=None, description="操作后的使用次数；未取得时省略。")
    miss_count: int | None = Field(default=None, description="操作后的陌生次数；未取得时省略。")


class WordStatsResult(OmitNoneResponse):
    """按原始输入下标返回计数操作结果。"""

    preserve_null = frozenset({"word"})
    index: int = Field(description="输入数组中的零基下标。")
    word: str | None = Field(description="单词原文；无法安全输出的文本为 null。")
    status: Literal["updated", "skipped", "failed"] = Field(description="updated 已执行，skipped 未执行，failed 执行失败。")
    reason: str | None = Field(default=None, description="跳过或失败原因；成功且无说明时省略。")
    counts: WordCounts | None = Field(default=None, description="实际取得的操作后计数；未取得任何计数时省略。")
