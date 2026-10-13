"""统计入口适配：将三个工具共用的内部统计结果映射为对外子模型。"""

from thoth.dto.word_stats import StatsResult
from thoth.dto.response.word_stats_response import WordCounts, WordStatsResult


def to_stats_results(rows: list[StatsResult]) -> list[WordStatsResult]:
    """转换逐项状态，只在实际取得计数时构造 counts，保留原下标和安全单词值。"""
    return [WordStatsResult(
        index=row.index, word=row.word, status=row.status, reason=row.reason,
        counts=WordCounts(usage_count=row.usage_count, miss_count=row.miss_count)
        if row.usage_count is not None or row.miss_count is not None else None,
    ) for row in rows]
