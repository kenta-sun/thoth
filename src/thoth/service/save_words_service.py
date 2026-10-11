"""save_words MCP 工具的专属 Service：解析校验、管理连接、保存并返回结果。"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Literal

import psycopg
from fastmcp.exceptions import ToolError

from thoth.common.config import get_settings
from thoth.dao.tag_tbl_mapper import TagTblMapper
from thoth.dao.word_tag_tbl_mapper import WordTagTblMapper
from thoth.dao.word_tbl_mapper import WordTblMapper
from thoth.db.connection import DatabaseError, open_connection
from thoth.dto.word import SaveResult, WordBatchResult, WordInput, WordItemResult
from thoth.entity import WordEntity, WordTagEntity
from thoth.utils.json_utils import reject_json_constant, unique_json_object

INFORMATION_FIELDS = ("common_form", "hiragana", "meaning")
ALLOWED_FIELDS = {"word", *INFORMATION_FIELDS, "operation", "tags"}


def save_words(text: str) -> dict[str, list[dict[str, Any]]]:
    """解析单词 JSON 数组并保存，按输入顺序返回 results。

    单项失败保留在结果中；格式、配置、连接或批量查询失败抛出 ToolError。
    本次调用共用一条连接，结束时关闭；每项单词及标签写入由 Service 独立提交或回滚。
    """
    try:
        # 先解析，格式错误时不读取配置或连接数据库。
        items = parse_words_text(text)
        settings = get_settings()
        with open_connection(settings) as connection:
            return serialize_word_batch(
                save_word_batch(items, connection, operator=settings.operator)
            )
    except (ValueError, DatabaseError) as exc:
        # 保持整批错误的对外语义，数据库错误已由底层脱敏。
        raise ToolError(str(exc)) from exc


def parse_words_text(text: str) -> list[WordInput]:
    """解析非空 JSON 数组，返回与输入顺序一致的 WordInput 列表。

    整批格式错误抛出 ValueError；单项错误写入 error 并保留可输出的 word，
    不阻止其他项继续处理。重复键、非标准数值和过深嵌套均视为格式错误。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text 必须是非空 JSON 数组字符串。")
    try:
        # JSON 钩子对所有嵌套对象生效，避免重复键覆盖或 NaN 等值绕过协议。
        items = json.loads(
            text,
            object_pairs_hook=unique_json_object,
            parse_constant=reject_json_constant,
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
    """校验单项字段、操作和文本类型，返回包含 WordEntity 的请求对象。

    非法输入抛出 ValueError。信息字段缺失、null 或纯空白归一为 None，
    表示更新时忽略；tags 必须是非空数组并按首次出现去重。
    实际新增所需的完整性与标签存在性由保存流程检查。此函数不访问数据库。"""
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
    # 保留 word 原文用于精确匹配；ID 和审计字段由 DAO 返回的数据库实体提供。
    return WordInput(
        entity=WordEntity(
            word=word,
            common_form=_information_value(item, "common_form"),
            hiragana=_information_value(item, "hiragana"),
            meaning=_information_value(item, "meaning"),
        ),
        action=action,
        tags=_validate_tags(item.get("tags")),
    )


def _validate_tags(value: Any) -> tuple[str, ...]:
    """校验必填非空标签数组并按首次出现去重；不改大小写或空格，不查询数据库。"""
    if not isinstance(value, list) or not value:
        raise ValueError("tags 必填，且必须是至少包含一个标签编码的非空数组。")
    for code in value:
        if not isinstance(code, str) or re.fullmatch(r"[A-Za-z0-9_]{1,32}", code) is None:
            raise ValueError("tags 中每个编码必须是 1～32 位英文字母、数字或下划线组成的字符串。")
    return tuple(dict.fromkeys(value))


def _information_value(item: dict[str, Any], name: str) -> str | None:
    """校验并提取信息字段；空值返回 None，非法类型或数据库文本抛出 ValueError。"""
    value = item.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} 必须是字符串或 null。")
    if value is not None:
        _validate_database_text(name, value)
    # 仅用 strip 判断空值，保留非空原文；None 交给 DAO 作局部更新的忽略标记。
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
    """按输入顺序将错误项和重复项转为失败结果，仅保留可进入 DAO 的请求。

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


class MissingWordFieldsError(ValueError):
    """Service 在实际新增前报告缺失的信息字段。"""

    def __init__(self, fields: tuple[str, ...]) -> None:
        """保留缺失字段的顺序，供 MCP 响应输出 fields。"""
        # 新增必填但未提供有效值的信息字段名。
        self.fields = fields
        super().__init__(f"需要新增单词，但以下字段缺失或为空：{', '.join(fields)}。")


def _database_error(message: str, exc: psycopg.Error) -> DatabaseError:
    """构造脱敏数据库错误，仅保留场景和 SQLSTATE，不暴露 SQL、参数或连接信息。"""
    code = f"（SQLSTATE {exc.sqlstate}）" if exc.sqlstate else ""
    return DatabaseError(f"{message}{code}，请稍后重试。")


def _save_word_record(
    request: WordInput, repository: WordTblMapper, *, exists: bool
) -> SaveResult:
    """在当前事务内决定新增、更新或跳过，处理批量查重后的并发新增和外部删除。

    标签已由调用方验证存在；exists 仅表示批量读取结果，不保证记录仍存在。
    更新取得的单词行锁必须持有至标签替换完成，防止并发替换混合标签集合。
    """
    if exists and request.action == "create":
        return SaveResult("skipped", "单词已存在，未覆盖已有信息。")
    if not exists:
        missing = tuple(
            name for name in INFORMATION_FIELDS
            if getattr(request.entity, name) is None
        )
        if missing:
            raise MissingWordFieldsError(missing)
        inserted = repository.insert(request.entity)
        if inserted is not None:
            return SaveResult("created", entity=inserted)
        # 查重后并发新增仍遵守 create 不覆盖、update 合并字段的规则。
        if request.action == "create":
            return SaveResult("skipped", "单词已存在，未覆盖已有信息。")
    # 仅修改标签也执行 UPDATE，更新审计字段并取得单词行锁。
    updated = repository.update(request.entity)
    if updated is None:
        raise DatabaseError("保存期间单词记录发生变化，请重试。")
    return SaveResult("updated", entity=updated)


def _save_word_item(
    request: WordInput,
    repository: WordTblMapper,
    tag_mapper: TagTblMapper,
    word_tag_mapper: WordTagTblMapper,
    connection: psycopg.Connection,
    *,
    index: int,
    exists: bool,
    operator: str,
) -> WordItemResult:
    """以单个单词为事务边界保存信息和完整标签列表，提交后才返回成功。

    标签缺失、必填字段缺失、驱动或提交失败先回滚再转为 failed；其他异常向上
    传播但仍回滚。各 Mapper 使用同一连接，任何关联插入失败均恢复原单词及旧标签。
    """
    try:
        with connection.transaction():
            # 即使 create 将跳过已有词，也要求传入的标签全部合法且存在。
            existing_tags = {
                tag.code for tag in tag_mapper.find_by_codes(list(request.tags))
            }
            missing_tags = [code for code in request.tags if code not in existing_tags]
            if missing_tags:
                raise ValueError(f"标签不存在：{', '.join(missing_tags)}。请使用已有的合适标签。")
            saved = _save_word_record(request, repository, exists=exists)
            if saved.status != "skipped":
                if saved.entity is None or saved.entity.id is None:
                    raise DatabaseError("保存单词未返回有效 ID，请重试。")
                # 一律删除后重建，不做差量合并；删除及所有插入与单词写入共同回滚。
                word_id = saved.entity.id
                word_tag_mapper.delete_by_word_id(word_id)
                word_tag_mapper.insert_many([
                    WordTagEntity(
                        word_id=word_id, tag_code=code,
                        created_by=operator, updated_by=operator,
                    )
                    for code in request.tags
                ])
        return WordItemResult(
            index=index, word=request.entity.word,
            status=saved.status, reason=saved.reason,
        )
    except MissingWordFieldsError as exc:
        return WordItemResult(
            index=index, word=request.entity.word, status="failed",
            reason=str(exc), fields=exc.fields,
        )
    except (ValueError, DatabaseError, psycopg.Error) as exc:
        # 必须在 transaction 上下文退出后转换错误，避免吞掉异常而提交部分修改。
        error = (
            _database_error("保存单词及标签失败", exc)
            if isinstance(exc, psycopg.Error) else exc
        )
        return WordItemResult(
            index=index, word=request.entity.word, status="failed", reason=str(error)
        )


def save_word_batch(
    items: list[WordInput], connection: psycopg.Connection,
    *, operator: str = "THOTH_MCP",
) -> WordBatchResult:
    """批量查询有效词，再在同一连接上逐项开启独立事务保存单词及标签。

    items 为 parse_words_text 校验后的请求；空列表或全部无效时不访问数据库。
    connection 必须启用 autocommit 且没有外层事务，保证每项能独立提交。
    operator 同时用于单词和关联表的审计字段。
    批量查询失败抛出 DatabaseError，尚未写入；单项失败则保留结果并继续下一项。
    """
    repository = WordTblMapper(connection, operator=operator)
    tag_mapper = TagTblMapper(connection)
    word_tag_mapper = WordTagTblMapper(connection)
    prepared = _prepare_word_items(items)
    words = [
        word for item in prepared
        if isinstance(item, WordInput) and (word := item.entity.word) is not None
    ]
    try:
        existing_words = {
            entity.word for entity in repository.find_existing_words(words)
        } if words else set()
    except psycopg.Error as exc:
        raise _database_error("查询已有单词失败", exc) from exc
    return WordBatchResult(results=[
        item if isinstance(item, WordItemResult) else _save_word_item(
            item, repository, tag_mapper, word_tag_mapper, connection,
            index=index, exists=item.entity.word in existing_words, operator=operator,
        )
        for index, item in enumerate(prepared)
    ])


def serialize_word_batch(batch: WordBatchResult) -> dict[str, list[dict[str, Any]]]:
    """将批次结果转为 MCP 响应字典，不修改原对象。

    保留 index、word、status；word 为 None 时输出 null。
    reason、fields 为 None 时省略，fields 元组转为数组；空批次返回空 results。"""
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
