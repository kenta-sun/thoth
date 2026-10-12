"""统计输入公共服务：解析为预处理 DTO，供三个专属 Service 执行后合并输出。"""

import json
from typing import Any

import psycopg

from thoth.db.connection import DatabaseError
from thoth.dto.word_stats import WordListItem, WordListPreprocessResult, StatsResult
from thoth.utils.json_utils import reject_json_constant, unique_json_object


def parse_word_list_text(text: str) -> WordListPreprocessResult:
    """包装原始数组并过滤、去重，不构造数据库实体，不读取配置或访问数据库。

    Args:
        text: 单词 JSON 字符串数组，空数组允许，元素可以包含待跳过的无效值。

    Returns:
        整批格式无效时 status 为 stop，message 为原因，各列表为空；正常时为
        continue。待处理项引用原始对象，跳过项携带原始下标，原始值不对外序列化。
    """
    if not isinstance(text, str) or not text.strip():
        return WordListPreprocessResult("stop", "text 必须是 JSON 数组字符串。")
    try:
        raw = json.loads(text, object_pairs_hook=unique_json_object,
                         parse_constant=reject_json_constant)
    except json.JSONDecodeError as exc:
        return WordListPreprocessResult("stop", f"text 不是合法 JSON：第 {exc.lineno} 行、第 {exc.colno} 列格式错误。")
    except RecursionError:
        return WordListPreprocessResult("stop", "JSON 嵌套层级过深。")
    except ValueError as exc:
        return WordListPreprocessResult("stop", str(exc))
    if not isinstance(raw, list):
        return WordListPreprocessResult("stop", "text 必须包含 JSON 数组。")
    original = [WordListItem(index, value) for index, value in enumerate(raw)]
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
    return WordListPreprocessResult("continue", original_items=original,
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


def serialize_stats(results: list[StatsResult]) -> dict[str, list[dict[str, Any]]]:
    """返回逐项结果，只输出实际取得的计数；None 字段省略，word 除外。"""
    rows = []
    for item in results:
        row = {"index": item.index, "word": item.word, "status": item.status}
        if item.reason is not None:
            row["reason"] = item.reason
        counts = {field: value for field in ("miss_count", "usage_count")
                  if (value := getattr(item, field)) is not None}
        if counts:
            row["counts"] = counts
        rows.append(row)
    return {"results": rows}
