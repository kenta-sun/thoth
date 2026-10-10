"""单词业务层：解析 JSON、校验输入并组织批量保存。

JSON 数组先转换为持有 WordEntity 的 WordInput；通过业务校验且不重复的
单词集中查询存在性，随后逐项将 entity 交给仓储保存。业务结果以 WordItemResult、WordBatchResult
传递，最后由 serialize_word_batch 转成 MCP 协议需要的 JSON 字典。
entity 本身只承载数据，输入要求在本模块校验，新增完整性由仓储按实际分支判断。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from thoth.db.connection import DatabaseError
from thoth.db.word_repo import MissingWordFieldsError, WordRepository
from thoth.entities import WordEntity

INFORMATION_FIELDS = ("common_form", "hiragana", "meaning")
ALLOWED_FIELDS = {"word", *INFORMATION_FIELDS, "operation"}


@dataclass(frozen=True, slots=True)
class WordInput:
    """承载一项解析结果；单词字段共用 entity，操作和错误属于请求信息。"""

    # 单词记录；有效输入保留本次提供的字段，错误项仅保留可输出的 word。
    entity: WordEntity
    # create 表示不覆盖已有词，update 表示局部更新；未传 operation 时默认 create。
    action: Literal["create", "update"] = "create"
    # 逐项输入错误；None 表示输入校验通过，仍需检查批内重复和保存条件。
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WordItemResult:
    """承载单项处理结果，使批次中的失败和成功均能按原位置返回。"""

    # 在原 JSON 数组中的零基下标，也用于定位无法返回 word 的错误项。
    index: int
    # 输入中的原始单词；缺失、类型错误或无法编码为 UTF-8 时为 None。
    word: str | None
    # created 新增、updated 更新、skipped 无需写入、failed 输入或保存失败。
    status: Literal["created", "updated", "skipped", "failed"]
    # 失败或跳过原因；None 表示没有需要返回的说明。
    reason: str | None = None
    # 实际新增时缺少的信息字段名；None 表示该项没有缺失字段报告。
    fields: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class WordBatchResult:
    """承载整批处理结果，不将数据库记录或审计字段暴露为接口结果。"""

    # 按原输入顺序保存每项结果，包含未进入仓储的无效项和重复项。
    results: list[WordItemResult]


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """将 JSON 对象的键值对还原为字典；重复键抛出 ValueError，避免静默覆盖。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 对象包含重复字段：{key!r}。")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    """拒绝解析器默认容许的 NaN、Infinity 等非标准 JSON 数值，抛出 ValueError。"""
    raise ValueError(f"JSON 不允许使用 {value}。")


def parse_words_text(text: str) -> list[WordInput]:
    """在 JSON 输入边界构造 entity，并保留每项业务校验结果。

    先确认整批符合 JSON 数组协议，再逐项校验；单项失败仍占据原位置，
    使后续批量保存可以继续处理其他项，并将错误返回给调用方。

    Args:
        text: 非空 JSON 数组字符串，每个元素应为单词对象。

    Returns:
        与原数组顺序一致的请求列表。有效项的 error 为 None；无效项的
        error 为错误说明，entity 仅保留能够安全输出的原始 word。

    Raises:
        ValueError: 输入不是非空 JSON 数组、格式错误、含重复键或非标准
            数值，或者嵌套层级过深。单项业务校验错误不会导致整批抛出。
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text 必须是非空 JSON 数组字符串。")
    try:
        # JSON 钩子对所有嵌套对象生效，避免重复键覆盖或 NaN 等值绕过协议。
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
    # 此处起只隔离逐项错误；保留 word 以便后续识别有效项与无效项之间的重复。
    requests: list[WordInput] = []
    for item in items:
        try:
            requests.append(validate_word_input(item))
        except ValueError as exc:
            requests.append(
                WordInput(entity=WordEntity(word=_item_word(item)), error=str(exc))
            )
    return requests


def _validate_action(item: dict[str, Any]) -> Literal["create", "update"]:
    """读取单词对象的操作；省略时返回 create，结构或动作非法时抛出 ValueError。"""
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
    """检查空字符和 UTF-8 编码；失败时用字段名 name 生成 ValueError。"""
    if "\x00" in value:
        raise ValueError(f"{name} 不允许包含空字符（U+0000）。")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} 包含无法编码为 UTF-8 的字符。") from exc


def validate_word_input(item: Any) -> WordInput:
    """执行单项输入校验，将允许的单词字段放入共用的 WordEntity。

    本函数检查字段白名单、word、操作格式和文本类型，不访问数据库。
    common_form、hiragana、meaning 可省略；只有仓储确定实际新增时，
    才检查这些信息是否齐全，因而已有词的局部更新无需提供完整记录。

    Args:
        item: JSON 数组中的原始元素，预期为单词对象。

    Returns:
        error 为 None 的请求对象。信息字段缺失、为 null 或只有空白时
        归一为 None，在局部更新中表示忽略该字段，不表示将数据库字段写空。

    Raises:
        ValueError: 元素不是对象、含不允许的字段，或字段值及操作格式非法。
    """
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
    # 保留 word 原文用于精确匹配；ID 和审计字段由仓储返回的数据库实体提供。
    return WordInput(
        entity=WordEntity(
            word=word,
            common_form=_information_value(item, "common_form"),
            hiragana=_information_value(item, "hiragana"),
            meaning=_information_value(item, "meaning"),
        ),
        action=action,
    )


def _information_value(item: dict[str, Any], name: str) -> str | None:
    """校验并提取信息字段；空值返回 None，非法类型或数据库文本抛出 ValueError。"""
    value = item.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} 必须是字符串或 null。")
    if value is not None:
        _validate_database_text(name, value)
    # 仅用 strip 判断空值，保留非空原文；None 交给仓储作局部更新的忽略标记。
    return value if value is not None and value.strip() else None


def _item_word(item: Any) -> str | None:
    """提取错误项中可安全输出的原始 word；缺失、非字符串或无效 Unicode 返回 None。"""
    if isinstance(item, dict) and isinstance(item.get("word"), str):
        word = item["word"]
        try:
            word.encode("utf-8")
        except UnicodeEncodeError:
            # 无效 Unicode 不能再带入 MCP 返回值；用 index 定位该项。
            return None
        return word
    return None


def _duplicate_words(items: list[WordInput]) -> set[str]:
    """统计所有请求中非 None 的原始 word，返回出现至少两次的单词集合。"""
    # 错误项也参与统计，避免同一 word 的有效项在其他重复项失败时仍被保存。
    counts = Counter(
        word for item in items if (word := item.entity.word) is not None
    )
    return {word for word, count in counts.items() if count > 1}


def _prepare_word_items(
    items: list[WordInput],
) -> list[WordInput | WordItemResult]:
    """按输入顺序将错误项和重复项转为失败结果，仅保留可进入仓储的请求。

    items 应为解析后的请求列表；已有 error 优先作为失败原因，其他重复项
    使用重复说明。返回列表与输入等长，空输入返回空列表，不访问数据库。
    """
    duplicates = _duplicate_words(items)
    prepared: list[WordInput | WordItemResult] = []
    for index, item in enumerate(items):
        reason = item.error
        if reason is None and item.entity.word in duplicates:
            reason = "同一批次不允许重复的 word；该词的所有重复项均未保存。"
        if reason is not None:
            prepared.append(
                WordItemResult(
                    index=index, word=item.entity.word, status="failed", reason=reason
                )
            )
        else:
            prepared.append(item)
    return prepared


def _save_word_item(
    request: WordInput, repository: WordRepository, *, index: int, exists: bool
) -> WordItemResult:
    """保存一个已通过输入及重复检查的请求，将预期保存异常转为失败结果。

    Args:
        request: 携带待保存 entity 和操作类型的有效请求。
        repository: 执行实际数据库写入的仓储；该调用可能新增或更新记录。
        index: 请求在原数组中的下标，原样写入处理结果。
        exists: 批量查询时该 word 是否已存在，供仓储选择保存分支。

    Returns:
        created、updated 或 skipped 结果；缺少新增字段、业务值错误和
        DatabaseError 转为 failed，缺失字段异常还会携带 fields。
        其他未预期异常继续向上传播，不被伪装成业务失败。
    """
    # 将同一个 entity 交给仓储；单项预期失败只影响当前结果，不中断后续项。
    try:
        saved = repository.save(
            request.entity, action=request.action, exists=exists
        )
    except MissingWordFieldsError as exc:
        return WordItemResult(
            index=index, word=request.entity.word, status="failed",
            reason=str(exc), fields=tuple(exc.fields),
        )
    except (ValueError, DatabaseError) as exc:
        return WordItemResult(
            index=index, word=request.entity.word, status="failed", reason=str(exc)
        )
    return WordItemResult(
        index=index, word=request.entity.word, status=saved.status, reason=saved.reason
    )


def save_word_batch(
    items: list[WordInput], repository: WordRepository
) -> WordBatchResult:
    """一次查询有效单词是否存在，再逐项保存并返回与输入顺序一致的结果。

    Args:
        items: 经 parse_words_text 或 validate_word_input 处理的请求；
            可含带 error 的无效项，空列表返回空结果且不访问仓储。
        repository: 提供批量查询及单项保存的仓储，负责实际数据库操作。

    Returns:
        包含每项成功、跳过或失败状态的批次结果。无效项和重复项不会写入；
        全部项无效时也不查询数据库，正常项的预期保存失败不会阻止后续项。

    Raises:
        DatabaseError: 批量存在性查询失败；该查询位于所有写入之前，失败时
            整批停止且尚未写入任何项。单项保存的数据库错误保留在结果中。
    """
    # 先固定每个输入的位置并隔离失败项，查询范围仅包含允许继续保存的单词。
    prepared = _prepare_word_items(items)
    words = [
        word for item in prepared
        if isinstance(item, WordInput) and (word := item.entity.word) is not None
    ]
    existing_words = {
        entity.word for entity in repository.find_existing_words(words)
    } if words else set()
    # 沿原顺序合并预先生成的失败结果和保存结果，保证 index 与请求一一对应。
    return WordBatchResult(results=[
        item if isinstance(item, WordItemResult) else _save_word_item(
            item, repository, index=index, exists=item.entity.word in existing_words
        )
        for index, item in enumerate(prepared)
    ])


def serialize_word_batch(batch: WordBatchResult) -> dict[str, list[dict[str, Any]]]:
    """在 JSON 输出边界转换结果对象，保持既有 MCP 响应结构。

    Args:
        batch: 业务层产生的批次结果，包含按原输入顺序排列的单项结果。

    Returns:
        以 results 为唯一顶层键的字典；每项保留 index、word、status，
        word 为 None 时仍输出 null。reason、fields 仅在非 None 时输出，
        fields 元组转换为 JSON 数组；空批次输出空 results 数组。
        返回值不包含 entity、数据库主键或审计字段，也不修改原结果对象。
    """
    results: list[dict[str, Any]] = []
    for item in batch.results:
        result: dict[str, Any] = {
            "index": item.index, "word": item.word, "status": item.status,
        }
        # 省略未提供的可选键，而不是输出 null，保持接口既有的条件字段行为。
        if item.reason is not None:
            result["reason"] = item.reason
        if item.fields is not None:
            result["fields"] = list(item.fields)
        results.append(result)
    return {"results": results}
