"""单词数据传输对象：供业务层承载解析请求、保存中间结果和批次结果。

单词表字段由 WordEntity 承载，操作指令和处理状态不作为表字段保存。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from thoth.entity import WordEntity


@dataclass(frozen=True, slots=True)
class WordInput:
    """承载一项解析结果，包含单词实体、标签编码、操作类型及输入错误。"""

    # 单词记录；有效输入保留本次提供的字段，错误项仅保留可输出的 word。
    entity: WordEntity
    # 完整的新标签编码集合；有效请求至少一个且已去重，错误项默认为空。
    tags: tuple[str, ...] = ()
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

    # 按原输入顺序保存每项结果，包含未进入 DAO 的无效项和重复项。
    results: list[WordItemResult]


@dataclass(frozen=True, slots=True)
class SaveResult:
    """承载 Service 编排保存的结果，供业务层转换为逐项对外响应。"""

    # created 表示已新增，updated 表示已修改，skipped 表示本次没有写入。
    status: Literal["created", "updated", "skipped"]
    # 跳过时说明原因；成功新增或修改时为 None。
    reason: str | None = None
    # 写入后由数据库返回的完整记录，含生成值；跳过写入时为 None。
    entity: WordEntity | None = None
