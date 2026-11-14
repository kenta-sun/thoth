"""add_update_words MCP 工具的专属 Service：归一化内部指令、管理连接并返回业务保存结果。"""

from __future__ import annotations

from collections import Counter

import psycopg

from thoth.common.config import get_settings
from thoth.dao.tag_tbl_mapper import TagTblMapper
from thoth.dao.word_tag_tbl_mapper import WordTagTblMapper
from thoth.dao.word_tbl_mapper import WordTblMapper
from thoth.db.connection import DatabaseError, open_connection
from thoth.dto.word import SaveResult, WordBatchResult, WordInput, WordItemResult, WordWriteCommand
from thoth.entity import WordEntity, WordTagEntity, WordFamEntity
from thoth.dao.word_fam_tbl_mapper import WordFamTblMapper
from thoth.common.tags import TAG_DEFINITIONS, FAMILIARITY_TAG_DEFINITIONS
from thoth.service.user_lookup_service import validate_username, require_user

INFORMATION_FIELDS = ("common_form", "hiragana", "meaning")


def add_update_words(words: list[WordWriteCommand], username: str) -> WordBatchResult:
    """归一化写入指令并逐项保存，每项单词、普通标签与用户熟悉度共用独立事务。

    Args:
        words: 结构已校验的内部写入指令，不包含接口模型。
        username: 已存在的用户名，指定本批熟悉度归属。

    Returns:
        按输入顺序排列的业务结果；单项失败不会中断其他项。

    Raises:
        ValueError: 用户名非法或用户不存在。
        DatabaseError: 配置、连接或批量查询失败，消息已脱敏。
    """
    validate_username(username)
    items = prepare_word_inputs(words)
    settings = get_settings()
    with open_connection(settings) as connection:
        user = require_user(connection, username)
        return save_word_batch(items, connection, user_id=user.id)


def prepare_word_inputs(words: list[WordWriteCommand]) -> list[WordInput]:
    """将内部写入指令归一化为表实体与操作，逐项保留业务输入错误。

    空指令列表返回空列表，不访问数据库；错误项仍保留安全的单词原文以参与批内查重。
    """
    requests = []
    for item in words:
        try:
            requests.append(validate_word_input(item))
        except ValueError as exc:
            requests.append(WordInput(entity=WordEntity(word=_safe_word(item.word)), error=str(exc)))
    return requests


def _validate_database_text(name: str, value: str) -> None:
    """检查空字符和 UTF-8 编码；失败时用字段名生成业务输入错误。"""
    if "\x00" in value:
        raise ValueError(f"{name} 不允许包含空字符（U+0000）。")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} 包含无法编码为 UTF-8 的字符。") from exc


def validate_word_input(item: WordWriteCommand) -> WordInput:
    """检查业务文本、归一化信息字段并去重标签，构造单词实体。

    请求结构由入口校验；None 或纯空白信息表示更新时忽略，非空原文保持不变。
    标签为 None 表示更新时保留原标签；新增完整性和标签存在性在实际保存时检查。
    """
    if not item.word.strip():
        raise ValueError("word 必填，且必须是非空字符串。")
    _validate_database_text("word", item.word)
    return WordInput(
        entity=WordEntity(
            word=item.word,
            common_form=_information_value(item.common_form, "common_form"),
            hiragana=_information_value(item.hiragana, "hiragana"),
            meaning=_information_value(item.meaning, "meaning"),
        ),
        action=item.action, fam=item.fam,
        tags=tuple(dict.fromkeys(item.tags)) if item.tags is not None else None,
    )


def _information_value(value: str | None, name: str) -> str | None:
    """校验信息文本，None 或纯空白表示更新时保留原值，非空值保留原文。"""
    if value is not None:
        _validate_database_text(name, value)
    return value if value is not None and value.strip() else None


def _safe_word(word: str) -> str | None:
    """保留错误项中可安全返回的单词原文，无效 Unicode 返回 None。"""
    try:
        word.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return word


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
    """按输入顺序将错误项和重复项转为失败结果，仅保留可进入保存流程的请求。

    items 应为归一化后的业务输入列表；已有 error 优先作为失败原因，其他重复项
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


def _validate_new_word_fields(entity: WordEntity, tags: tuple[str, ...] | None) -> None:
    """检查新增信息及非空标签，缺失时汇总为 MissingWordFieldsError。"""
    missing = tuple(
        name for name in INFORMATION_FIELDS
        if getattr(entity, name) is None
    )
    if not tags:
        missing += ("tags",)
    if missing:
        raise MissingWordFieldsError(missing)


def _insert_word_record(
    request: WordInput, repository: WordTblMapper
) -> SaveResult | None:
    """在当前事务内校验新增字段并插入，成功返回 created，同名并发冲突返回 None。

    create 和 update 的首次新增共用此流程；字段缺失或数据库错误向上传递，
    冲突后的跳过或更新由调用方按业务场景决定。
    """
    _validate_new_word_fields(request.entity, request.tags)
    inserted = repository.insert(request.entity)
    if inserted is None:
        _reject_deleted(repository.find_by_word_for_update(request.entity.word))
        return None
    return SaveResult("created", entity=inserted)


def _update_word_record(entity: WordEntity, repository: WordTblMapper) -> SaveResult:
    """在当前事务内局部更新并返回 updated，未更新到记录时抛出 DatabaseError。

    None 信息字段保留原值；取得的单词行锁须持有至标签替换完成，
    防止并发替换混合标签集合。
    """
    # 仅修改标签也执行 UPDATE，更新审计字段并取得单词行锁。
    updated = repository.update(entity)
    if updated is None:
        raise DatabaseError("保存期间单词记录发生变化，请重试。")
    return SaveResult("updated", entity=updated)


def _save_word_record(
    request: WordInput, repository: WordTblMapper, *, exists: bool
) -> SaveResult:
    """在当前事务内按 create、update 场景分别编排新增、更新和跳过。

    request 已通过输入和标签校验，action 只会是 create 或 update。
    exists 是批量查重时的存在性；实际插入冲突仍须按各场景处理。
    """
    if request.action == "create":
        if exists:
            return SaveResult("skipped", "单词已存在，未覆盖已有信息。")
        else:
            inserted = _insert_word_record(request, repository)
            if inserted is None:
                # 并发新增冲突时跳过，不覆盖已有记录。
                return SaveResult("skipped", "单词已存在，未覆盖已有信息。")
            else:
                return inserted
    else:  # update 对已有词局部更新，对不存在的词尝试新增。
        if exists:
            return _update_word_record(request.entity, repository)
        else:
            inserted = _insert_word_record(request, repository)
            if inserted is None:
                # 并发新增冲突时，按 update 语义更新当前记录。
                return _update_word_record(request.entity, repository)
            else:
                return inserted


def _reject_deleted(entity: WordEntity | None) -> None:
    """优先拒绝已删除单词，不允许更新共享信息或用户熟悉度。"""
    if entity is not None and entity.status_code == "D":
        raise ValueError("该单词已被删除，不允许操作。")


def _validate_tags(request: WordInput, mapper: TagTblMapper) -> None:
    """先报告全部不存在的标签，再检查普通标签和熟悉度标签的用途。"""
    codes = list(dict.fromkeys([*(request.tags or ()), *([request.fam] if request.fam is not None else [])]))
    if not codes:
        return
    existing = {tag.code for tag in mapper.find_by_codes(codes)}
    missing = [code for code in codes if code not in existing]
    if missing:
        raise ValueError(f"标签不存在：{', '.join(missing)}。")
    ordinary = {tag.code for tag in TAG_DEFINITIONS}
    familiarity = {tag.code for tag in FAMILIARITY_TAG_DEFINITIONS}
    invalid = [code for code in (request.tags or ()) if code not in ordinary]
    if invalid:
        raise ValueError(f"tags 只接受普通标签，类型不符：{', '.join(invalid)}。")
    if request.fam is not None and request.fam not in familiarity:
        raise ValueError(f"fam 只接受熟悉度标签，类型不符：{request.fam}。")


def _save_familiarity(connection: psycopg.Connection, user_id: int, word_id: int, code: str) -> str:
    """持有单词行锁时新增或更新用户熟悉度；相同编码不更新审计字段。"""
    mapper = WordFamTblMapper(connection)
    current = mapper.find_for_update(user_id=user_id, word_id=word_id)
    if current is not None and current.tag_code == code:
        return "unchanged"
    mapper.save(WordFamEntity(user_id=user_id, word_id=word_id, tag_code=code))
    return "created" if current is None else "updated"


def _save_word_item(
    request: WordInput,
    repository: WordTblMapper,
    tag_mapper: TagTblMapper,
    word_tag_mapper: WordTagTblMapper,
    connection: psycopg.Connection,
    *,
    index: int,
    exists: bool,
    user_id: int,
) -> WordItemResult:
    """以单个单词为事务边界保存信息和完整标签列表，提交后才返回成功。

    调用方须提供无外层事务的 autocommit 连接，各 Mapper 必须共用该连接。
    先锁定单词并拒绝删除状态，再校验标签及保存；仅提供熟悉度时不更新共享词条。

    Args:
        request: 已通过输入校验和批内查重的请求；标签列表为 None 表示更新时保留原标签。
        repository: 单词表读写对象。
        tag_mapper: 标签字典查询对象。
        word_tag_mapper: 单词标签关联写入对象。
        connection: 用于开启本项事务的数据库连接。
        index: 原输入数组中的零基下标。
        exists: 批量查询时单词是否存在；保存时仍处理并发变化。
        user_id: 已存在的用户主键，限定熟悉度归属。

    Returns:
        提交后的保存结果；标签不存在、必填字段缺失或数据库错误均在回滚后
        转为 failed。跳过已有词时仍校验标签，但不修改单词或关联。

    Raises:
        Exception: 未归类的异常在事务回滚后向上传递。
    """
    try:
        with connection.transaction():
            # 先锁定并检查当前状态，防止标签写入期间单词被标记删除。
            current = repository.find_by_word_for_update(request.entity.word)
            _reject_deleted(current)
            if exists and current is None:
                raise DatabaseError("保存期间单词记录发生变化，请重试。")
            _validate_tags(request, tag_mapper)
            fam_status = None
            if (current is not None and request.action == "update" and request.fam is not None
                    and request.tags is None
                    and all(getattr(request.entity, field) is None for field in INFORMATION_FIELDS)):
                # 仅标注用户熟悉度，不触碰共享词条的内容和审计字段。
                saved = SaveResult("updated", entity=current)
            else:
                saved = _save_word_record(request, repository, exists=current is not None)
            if saved.status != "skipped":
                if saved.entity is None or saved.entity.id is None:
                    raise DatabaseError("保存单词未返回有效 ID，请重试。")
                if request.tags is not None:
                    # 显式提供标签时删除后重建，不做差量合并；与单词写入共同回滚。
                    word_id = saved.entity.id
                    word_tag_mapper.delete_by_word_id(word_id)
                    word_tag_mapper.insert_many([
                        WordTagEntity(
                            word_id=word_id, tag_code=code,
                        )
                        for code in request.tags
                    ])
                if request.fam is not None:
                    fam_status = _save_familiarity(connection, user_id, saved.entity.id, request.fam)
        return WordItemResult(
            index=index, word=request.entity.word,
            status=saved.status, reason=saved.reason, fam_status=fam_status,
        )
    except MissingWordFieldsError as exc:
        return WordItemResult(
            index=index, word=request.entity.word, status="failed",
            reason=str(exc), fields=exc.fields,
        )
    except (ValueError, DatabaseError, psycopg.Error) as exc:
        # 必须在 transaction 上下文退出后转换错误，避免吞掉异常而提交部分修改。
        error = (
            _database_error("保存单词、标签及熟悉度失败", exc)
            if isinstance(exc, psycopg.Error) else exc
        )
        return WordItemResult(
            index=index, word=request.entity.word, status="failed", reason=str(error)
        )


def save_word_batch(
    items: list[WordInput], connection: psycopg.Connection, *, user_id: int,
) -> WordBatchResult:
    """批量查询有效词，再在同一连接上逐项开启独立事务保存单词及标签。

    Args:
        items: prepare_word_inputs 返回的业务输入列表；空列表或全部无效时不访问数据库。
        connection: 已启用 autocommit 且没有外层事务的连接，保证每项独立提交。
        user_id: 已校验存在的用户主键，限定熟悉度记录归属。

    Returns:
        与输入等长且顺序一致的批次结果，单项失败保留在结果中并继续下一项。

    Raises:
        DatabaseError: 批量查重失败，此时尚未开始写入。
    """
    repository = WordTblMapper(connection)
    tag_mapper = TagTblMapper(connection)
    word_tag_mapper = WordTagTblMapper(connection)
    # 输入错误和批内重复先转为结果，仅将可保存的单词交给 DAO 批量查重。
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
    # 复用查重结果逐项保存；每项独立提交或回滚，并保留原输入位置。
    return WordBatchResult(results=[
        item if isinstance(item, WordItemResult) else _save_word_item(
            item, repository, tag_mapper, word_tag_mapper, connection,
            index=index, exists=item.entity.word in existing_words, user_id=user_id,
        )
        for index, item in enumerate(prepared)
    ])
