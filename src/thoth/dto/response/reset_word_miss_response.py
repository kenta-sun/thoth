"""reset_word_miss 响应：承载按输入顺序排列的统计结果。"""

from pydantic import Field
from thoth.dto.response.common import ResponseModel
from thoth.dto.response.word_stats_response import WordStatsResult


class ResetWordMissResponse(ResponseModel):
    """返回本次统计调用的逐项结果。"""

    results: list[WordStatsResult] = Field(description="按输入顺序排列的结果；空批次返回空数组。")
