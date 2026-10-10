"""仓储层负责单词表读写，把业务层传入的实体交给固定 SQL 保存。

业务层先批量查询已有实体，再逐项调用保存；仓储只在 SQL 参数绑定处使用字典，
查询及写入返回的记录均由驱动构造成 WordEntity。每次保存使用独立事务，
单项失败回滚后不会阻止同一连接继续处理下一项。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.rows import class_row

from thoth.db.connection import DatabaseError
from thoth.entities import WordEntity

# 按 word 原文一次查询本批已有记录，包含已标记删除的词；不加行锁，
# 因此结果只反映查询时的存在性，保存时仍需处理并发新增或外部删除。
_SQL_FIND_EXISTING_WORDS = """
SELECT id, word, common_form, hiragana, meaning, status_code,
       created_at, updated_at, created_by, updated_by
FROM word_tbl
WHERE word = ANY(%(words)s)
"""

# 仅写业务字段和操作者，id、状态和时间交给数据库默认值生成。
# word 的唯一约束配合 ON CONFLICT 避免并发新增时覆盖原记录；
# RETURNING 返回实际新增的完整行，发生冲突而未写入时不返回记录。
_SQL_INSERT_WORD = """
INSERT INTO word_tbl (word, common_form, hiragana, meaning, created_by, updated_by)
VALUES (%(word)s, %(common_form)s, %(hiragana)s, %(meaning)s, %(operator)s, %(operator)s)
ON CONFLICT (word) DO NOTHING
RETURNING id, word, common_form, hiragana, meaning, status_code,
          created_at, updated_at, created_by, updated_by
"""

# 只按 word 定位并更新三个信息字段及修改审计字段，不修改 word 或状态。
# COALESCE 把请求中的 None 视为“保留当前数据库值”，避免清空原值，
# 也避免使用批量查询时的旧实体覆盖其他请求刚修改的字段。
# UPDATE 由数据库取得行锁；RETURNING 用于取得实际结果并识别零行更新。
_SQL_UPDATE_WORD = """
UPDATE word_tbl
SET common_form = COALESCE(%(common_form)s, common_form),
    hiragana = COALESCE(%(hiragana)s, hiragana),
    meaning = COALESCE(%(meaning)s, meaning),
    updated_at = CURRENT_TIMESTAMP,
    updated_by = %(operator)s
WHERE word = %(word)s
RETURNING id, word, common_form, hiragana, meaning, status_code,
          created_at, updated_at, created_by, updated_by
"""


@dataclass(frozen=True, slots=True)
class SaveResult:
    """承载一次仓储保存的结果，交由业务层转换为逐项对外响应。"""

    # created 表示已新增，updated 表示已修改，skipped 表示本次没有写入。
    status: Literal["created", "updated", "skipped"]
    # 跳过时说明原因；成功新增或修改时为 None。
    reason: str | None = None
    # 写入后由数据库返回的完整记录，含生成值；跳过写入时为 None。
    entity: WordEntity | None = None


class MissingWordFieldsError(ValueError):
    """实际需要新增时，报告尚未提供有效值的信息字段。"""

    def __init__(self, fields: tuple[str, ...]) -> None:
        """记录缺失字段名及可展示的错误消息，fields 顺序供业务层原样返回。"""
        # 缺少新增值的字段名，不包含数据库记录内容。
        self.fields = fields
        super().__init__(f"需要新增单词，但以下字段缺失或为空：{', '.join(fields)}。")


class WordRepository:
    """在调用方管理的连接上查询和保存单词，不负责建立或关闭连接。

    连接必须启用 autocommit，批量查重不持有跨项事务；需要写入时，
    save 为该项单独建立事务并处理并发冲突。
    """

    def __init__(
        self, connection: psycopg.Connection, *, operator: str = "THOTH_MCP"
    ) -> None:
        """绑定已打开且启用 autocommit 的 connection，以 operator 写入审计字段。"""
        self._connection = connection
        self._operator = operator

    def find_existing_words(self, words: list[str]) -> list[WordEntity]:
        """一次读取本批已存在的完整记录，供业务层决定新增、修改或跳过。

        Args:
            words: 已通过业务校验且去除重复项的 word 原文；空列表不查询数据库。

        Returns:
            匹配的实体列表，包含已标记删除的记录；无匹配时为空列表。
            数据库未指定返回顺序，调用方应按实体的 word 判断存在性。
            查询不锁行，结果不能保证保存时该记录仍存在。

        Raises:
            DatabaseError: 查询发生驱动错误，消息仅保留安全描述和可用的 SQLSTATE。
        """
        if not words:
            return []
        try:
            # class_row 按结果列名传入实体构造函数，不依赖字段声明顺序。
            with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
                cursor.execute(_SQL_FIND_EXISTING_WORDS, {"words": words})
                return cursor.fetchall()
        except psycopg.Error as exc:
            # 对外消息不包含原始 SQL、参数或连接信息；异常链保留内部诊断原因。
            code = f"（SQLSTATE {exc.sqlstate}）" if exc.sqlstate else ""
            raise DatabaseError(f"查询已有单词失败{code}，请稍后重试。") from exc

    def save(
        self,
        entity: WordEntity,
        *,
        action: Literal["create", "update"],
        exists: bool,
    ) -> SaveResult:
        """根据批量存在性结果处理单项保存，并返回本次写入或跳过的结果。

        调用前应由业务层完成字段类型校验，并把缺失或空白的信息字段归一为 None。
        先处理无需写入的情况及新增必填检查，再在独立事务中新增或局部修改；
        查重后发生的并发新增交给唯一约束识别，避免覆盖 create 请求遇到的原记录。

        Args:
            entity: 本项请求的单词字段；修改时三个信息字段中的 None 表示保留原值。
                id、状态及审计字段不直接用于写入，数据库生成值从返回实体读取。
            action: create 在已存在时跳过；update 在已存在时修改，不存在时尝试新增。
            exists: 批量查询时是否已存在该 word，不代表持有行锁或保证当前仍存在。

        Returns:
            新增或修改时包含数据库返回实体的 SaveResult；跳过时仅含状态及原因。
            不会修改传入实体；发生写入时，本项在返回前独立提交。

        Raises:
            ValueError: action 不是 create 或 update。
            MissingWordFieldsError: 需要新增，但三个信息字段中仍有 None。
            DatabaseError: 数据库写入失败，或修改时记录已不存在；本项事务已回滚。
        """
        if action not in ("create", "update"):
            raise ValueError("action 仅允许 create 或 update。")

        # 按查重结果先处理跳过分支；已有词不受新增必填要求影响。
        if exists:
            if action == "create":
                return SaveResult("skipped", "单词已存在，未覆盖已有信息。")
            if all(
                value is None
                for value in (entity.common_form, entity.hiragana, entity.meaning)
            ):
                return SaveResult("skipped", "未提供需要修改的有效字段。")
        else:
            self._require_new_word_fields(entity)

        try:
            # 每项单独提交或回滚，失败不使后续项继承一个已失败的事务。
            with self._connection.transaction():
                # 写入的 RETURNING 行同样由 class_row 按列名还原为实体。
                with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
                    if exists:
                        return self._update(cursor, entity)

                    inserted = self._insert(cursor, entity)
                    if inserted is not None:
                        return SaveResult("created", entity=inserted)

                    # 唯一约束处理查询后发生的并发新增。create 不覆盖；
                    # update 用固定 UPDATE 合并本项字段，并由数据库取得行锁。
                    if action == "create":
                        return SaveResult("skipped", "单词已存在，未覆盖已有信息。")
                    return self._update(cursor, entity)
        except psycopg.Error as exc:
            # transaction 上下文已经回滚；只转换驱动错误的对外消息，
            # 不暴露 SQL、参数或连接信息，原异常仅作为内部异常链保留。
            code = f"（SQLSTATE {exc.sqlstate}）" if exc.sqlstate else ""
            raise DatabaseError(f"保存单词失败{code}，请稍后重试。") from exc

    def _parameters(self, entity: WordEntity) -> dict[str, str | None]:
        """在 SQL 绑定边界读取实体业务属性，返回固定参数及仓储配置的操作者。

        保留信息字段中的 None，供局部更新 SQL 判断是否修改；不绑定实体中的
        id、状态或时间，防止请求中的缺省值覆盖数据库生成值。
        """
        return {
            "word": entity.word,
            "operator": self._operator,
            "common_form": entity.common_form,
            "hiragana": entity.hiragana,
            "meaning": entity.meaning,
        }

    @staticmethod
    def _require_new_word_fields(entity: WordEntity) -> None:
        """检查已归一化实体的新增信息，缺少值时抛出 MissingWordFieldsError。

        仅在批量查询认为 word 不存在时调用；这里只检查 None，
        字段类型、空白字符串和 word 的合法性由调用前的业务校验负责。
        """
        missing = tuple(
            name
            for name, value in (
                ("common_form", entity.common_form),
                ("hiragana", entity.hiragana),
                ("meaning", entity.meaning),
            )
            if value is None
        )
        if missing:
            raise MissingWordFieldsError(missing)

    def _insert(
        self, cursor: psycopg.Cursor[WordEntity], entity: WordEntity
    ) -> WordEntity | None:
        """在当前项事务内新增实体，返回含数据库生成值的完整记录。

        cursor 须已配置 WordEntity 行工厂；None 表示 word 唯一约束冲突，
        未覆盖已有记录。驱动错误向上传递，由 save 统一回滚并转换对外消息。
        """
        cursor.execute(_SQL_INSERT_WORD, self._parameters(entity))
        return cursor.fetchone()

    def _update(
        self,
        cursor: psycopg.Cursor[WordEntity],
        entity: WordEntity,
    ) -> SaveResult:
        """在当前项事务内按 entity.word 局部修改，并返回实际更新后的实体。

        cursor 须已配置 WordEntity 行工厂；信息字段的 None 交给 SQL 保留原值。
        若 RETURNING 无记录，抛出 DatabaseError 触发本项回滚，避免将零行更新
        误报为成功；其他驱动错误由 save 转换为可对外展示的消息。
        """
        cursor.execute(_SQL_UPDATE_WORD, self._parameters(entity))
        updated = cursor.fetchone()
        if updated is None:
            # 当前工具不物理删除行。若外部操作在批量查询或新增冲突后删除了该行，
            # 明确报告失败，避免将零行更新误报为成功。
            raise DatabaseError("保存期间单词记录发生变化，请重试。")
        return SaveResult("updated", entity=updated)
