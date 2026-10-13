"""统计输入公共服务：过滤单词并构造预处理 DTO，供三个专属 Service 执行后合并输出。"""

from typing import Any

import psycopg

from thoth.db.connection import DatabaseError
from thoth.dto.word_stats import WordListItem, WordListPreprocessResult, StatsResult


def prepare_word_list(words: list[str]) -> WordListPreprocessResult:
    """过滤业务无效文本并去重，保持输入位置；空数组允许，不访问数据库。

    参数应为字符串列表；直接业务调用传入非列表时拒绝整批，元素的防御性检查
    保留逐项跳过结果。MCP 入口会在调用前拒绝非字符串元素。
    """
    if not isinstance(words, list):
        raise ValueError("words 必须是单词列表。")
    original = [WordListItem(index, value) for index, value in enumerate(words)]
    pending: list[WordListItem] = []
    skipped: list[StatsResult] = []
    first: dict[str, int] = {}
    for item in original:
        value = item.original_value
        word = _safe_word(value)
        reason = None
        if value is None:
            reason = "单词为空。"
        elif not isinstance(value, str):
            reason = "单词必须是字符串。"
        elif word is None:
            reason = "单词无法编码为 UTF-8。"
        elif not word.strip():
            reason = "单词为空或仅包含空白字符。"
        elif "\x00" in word:
            reason = "单词包含数据库不支持的空字符。"
        elif word in first:
            reason = f"重复单词，已由 index={first[word]} 的项处理。"
        if reason is not None:
            skipped.append(StatsResult(item.index, word, "skipped", reason))
        else:
            first[word] = item.index
            pending.append(item)
    return WordListPreprocessResult(original_items=original,
                                    pending_items=pending, skipped_results=skipped)


def _safe_word(value: Any) -> str | None:
    """返回可安全输出的原始字符串；非字符串或无法编码为 UTF-8 时返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value


def merge_stats_results(preprocessed: WordListPreprocessResult,
                        executed: list[StatsResult]) -> list[StatsResult]:
    """合并执行结果与预处理跳过项，按原下标排序，不修改输入 DTO 或列表。

    调用方须为每个 pending_items 元素提供一个执行结果，且保留其原始 index。
    """
    return sorted([*preprocessed.skipped_results, *executed], key=lambda item: item.index)


def stats_database_error(exc: psycopg.Error) -> DatabaseError:
    """将驱动错误脱敏，仅保留 SQLSTATE；不建议自动重试非幂等计数。"""
    code = f"（SQLSTATE {exc.sqlstate}）" if exc.sqlstate else ""
    return DatabaseError(f"统计操作失败{code}。")
