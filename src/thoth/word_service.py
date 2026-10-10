"""输入解析、字段校验与逐项保存；数据库操作交给仓储层。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from thoth.db.connection import DatabaseError
from thoth.db.word_repo import MissingWordFieldsError, WordRepository

INFORMATION_FIELDS = ("common_form", "hiragana", "meaning")
ALLOWED_FIELDS = {"word", *INFORMATION_FIELDS, "operation"}


@dataclass(frozen=True, slots=True)
class WordInput:
    word: str
    action: Literal["create", "update"]
    values: dict[str, str | None]


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 对象包含重复字段：{key!r}。")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON 不允许使用 {value}。")


def parse_words_text(text: str) -> list[Any]:
    """只检查整批的 JSON 格式，元素错误留给逐项处理。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text 必须是非空 JSON 数组字符串。")
    try:
        items = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"text 不是合法 JSON：第 {exc.lineno} 行、第 {exc.colno} 列格式错误。"
        ) from exc
    except RecursionError as exc:
        raise ValueError("JSON 嵌套层级过深。") from exc
    if not isinstance(items, list) or not items:
        raise ValueError("text 必须包含非空 JSON 数组。")
    return items


def _validate_action(item: dict[str, Any]) -> Literal["create", "update"]:
    if "operation" not in item:
        return "create"
    operation = item["operation"]
    if not isinstance(operation, dict):
        raise ValueError("operation 必须是对象，且只包含 action。")
    if set(operation) != {"action"}:
        raise ValueError("operation 必须且只能包含 action 字段。")
    action = operation["action"]
    if action not in ("create", "update"):
        raise ValueError("operation.action 仅允许 create 或 update。")
    return action


def _validate_database_text(name: str, value: str) -> None:
    """在批量查询前隔离 PostgreSQL 文本不能存储的字符。"""
    if "\x00" in value:
        raise ValueError(f"{name} 不允许包含空字符（U+0000）。")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} 包含无法编码为 UTF-8 的字符。") from exc


def validate_word_input(item: Any) -> WordInput:
    """校验字段白名单和类型；只有实际新增时才检查信息是否齐全。"""
    if not isinstance(item, dict):
        raise ValueError("每项必须是单词对象。")
    unknown = set(item) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"不允许的字段：{', '.join(repr(name) for name in sorted(unknown))}。")
    word = item.get("word")
    if not isinstance(word, str) or not word.strip():
        raise ValueError("word 必填，且必须是非空字符串。")
    _validate_database_text("word", word)

    action = _validate_action(item)
    values: dict[str, str | None] = {}
    for name in INFORMATION_FIELDS:
        value = item.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} 必须是字符串或 null。")
        if value is not None:
            _validate_database_text(name, value)
        # 仅用 strip 判断空值，保留非空原文；word 也按原文精确匹配。
        values[name] = value if value is not None and value.strip() else None
    return WordInput(word=word, action=action, values=values)


def _item_word(item: Any) -> str | None:
    if isinstance(item, dict) and isinstance(item.get("word"), str):
        word = item["word"]
        try:
            word.encode("utf-8")
        except UnicodeEncodeError:
            # 无效 Unicode 不能再带入 MCP 返回值；用 index 定位该项。
            return None
        return word
    return None


def _duplicate_words(items: list[Any]) -> set[str]:
    counts = Counter(word for item in items if (word := _item_word(item)) is not None)
    return {word for word, count in counts.items() if count > 1}


def _prepare_word_items(
    items: list[Any],
) -> tuple[list[dict[str, Any]], list[tuple[int, WordInput]]]:
    """先校验全部输入，只让通过校验且不重复的单词参与批量查询。"""
    duplicates = _duplicate_words(items)
    results: list[dict[str, Any]] = []
    requests: list[tuple[int, WordInput]] = []
    for index, item in enumerate(items):
        result: dict[str, Any] = {"index": index, "word": _item_word(item)}
        try:
            request = validate_word_input(item)
            if request.word in duplicates:
                raise ValueError("同一批次不允许重复的 word；该词的所有重复项均未保存。")
        except ValueError as exc:
            result.update(status="failed", reason=str(exc))
        else:
            requests.append((index, request))
        results.append(result)
    return results, requests


def _save_word_item(
    request: WordInput, repository: WordRepository, *, exists: bool
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        saved = repository.save(
            word=request.word, action=request.action, values=request.values, exists=exists
        )
    except MissingWordFieldsError as exc:
        result.update(status="failed", reason=str(exc), fields=list(exc.fields))
    except (ValueError, DatabaseError) as exc:
        result.update(status="failed", reason=str(exc))
    else:
        result["status"] = saved.status
        if saved.reason is not None:
            result["reason"] = saved.reason
    return result


def save_word_batch(
    items: list[Any], repository: WordRepository
) -> dict[str, list[dict[str, Any]]]:
    results, requests = _prepare_word_items(items)
    if not requests:
        return {"results": results}

    existing_words = repository.find_existing_words(
        [request.word for _, request in requests]
    )
    for index, request in requests:
        results[index].update(
            _save_word_item(request, repository, exists=request.word in existing_words)
        )
    return {"results": results}
