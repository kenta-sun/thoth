"""
数据模型模块。

本模块集中定义两类模型，二者刻意分开，避免大模型协议细节泄漏到业务代码里：

1. **大模型结构化输出模型**（Pydantic BaseModel）
   直接作为 OpenAI Structured Outputs 的 ``response_format``，
   由 SDK 负责把模型响应解析成强类型对象，业务代码不再手写 JSON 解析。
   注意：这类模型的字段一律不设默认值，因为 OpenAI 的严格模式要求
   所有属性都出现在 ``required`` 中，设默认值没有意义反而容易误导。

2. **流水线内部流转模型**（dataclass）
   仅在 Python 内部传递，不参与序列化，用 dataclass 更轻量。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field

# ============================================================
# 枚举
# ============================================================


class MemoryType(str, Enum):
    """
    记忆类型。

    当前只支持两类，且**刻意不落库**：memory 表没有类型字段，
    类型仅用于在精炼阶段选择对应的提示词。后续如需入库，
    再补 memory_type 字典表与 memory.type_code 字段即可。
    """

    # 关于用户本人的长期属性：身份、偏好、技能、所处状态等。
    PERSONAL = "PERSONAL"
    # 已经发生的事件：时间、地点、主体、动作、结果。
    EVENT = "EVENT"

    @property
    def label_zh(self) -> str:
        """返回中文名称，用于日志与命令行输出。"""
        return _MEMORY_TYPE_LABELS[self]


# 中文名称映射，单独放在枚举外部，避免被当成枚举成员。
_MEMORY_TYPE_LABELS: dict[MemoryType, str] = {
    MemoryType.PERSONAL: "个人信息",
    MemoryType.EVENT: "事件",
}


class ClassificationLabel(str, Enum):
    """
    分类阶段的判定结果。

    比 ``MemoryType`` 多一个 ``DROP``：凡是无法明确归入前两类的内容一律丢弃，
    严禁强行归类。丢弃项不入库、不进入返回结果。
    """

    PERSONAL = "PERSONAL"
    EVENT = "EVENT"
    DROP = "DROP"

    def to_memory_type(self) -> MemoryType | None:
        """
        转换为记忆类型。

        返回：
        - PERSONAL / EVENT 对应的 MemoryType；
        - DROP 返回 None，调用方据此跳过该条。
        """
        if self is ClassificationLabel.PERSONAL:
            return MemoryType.PERSONAL
        if self is ClassificationLabel.EVENT:
            return MemoryType.EVENT
        return None


# ============================================================
# 大模型结构化输出模型
# ============================================================


class CoarseExtractionResult(BaseModel):
    """
    步骤 1（粗提取）的输出。

    每个元素是一段「粗记忆」：允许啰嗦、允许保留原文措辞，
    重点是不丢信息，精炼交给后续步骤。
    """

    memories: list[str] = Field(
        description="从原文中提取出的粗记忆列表；没有任何值得记录的内容时返回空列表。"
    )


class ClassificationResult(BaseModel):
    """步骤 2（分类）的输出。"""

    label: ClassificationLabel = Field(description="判定结果：PERSONAL、EVENT 或 DROP。")
    reason: str = Field(description="做出该判定的简短理由，仅用于调试，不入库。")


class RefinementResult(BaseModel):
    """步骤 3（精炼）的输出。"""

    content: str = Field(description="精炼后的记忆正文，逻辑严谨、无冗余表述。")


class SummaryResult(BaseModel):
    """
    步骤 4（摘要）的输出。

    ``needs_resplit`` 是留给「重新拆分」功能的信号位：
    当一条记忆涵盖多个互不相关的主题、无法用一句话概括时置为 true。
    当前版本不实现重拆，只把这类记忆挂起并在结果中报告。
    """

    summary: str = Field(description="100 字以内的中文摘要。")
    needs_resplit: bool = Field(description="该条记忆是否过于散乱、需要重新拆分。")
    resplit_reason: str = Field(
        description="需要重新拆分的原因；不需要重拆时返回空字符串。"
    )


class DuplicateJudgement(BaseModel):
    """步骤 7（判重终裁）的输出。"""

    is_duplicate: bool = Field(description="新记忆是否与某条候选记忆表达同一事实。")
    duplicate_of_id: int | None = Field(
        description="判定重复时，命中的候选记忆 ID；不重复时返回 null。"
    )
    reason: str = Field(description="判定理由，会写入结果报告便于人工复核。")


# ============================================================
# 流水线内部流转模型
# ============================================================


@dataclass(slots=True)
class MemoryDraft:
    """
    一条记忆在流水线中的中间态。

    随着流水线推进逐步补全字段，最终由 pipeline 决定写库还是丢弃。
    """

    # 粗提取阶段得到的原始片段，保留用于排查提取质量问题。
    raw_content: str
    # 分类阶段判定出的类型。
    memory_type: MemoryType
    # 精炼后的正文，最终写入 memory_version.content。
    refined_content: str
    # 摘要，最终写入 memory.summary，同时是向量化与查重的唯一依据。
    summary: str


@dataclass(slots=True)
class CandidateMemory:
    """向量召回得到的候选记忆，仅含判重所需的最小字段。"""

    memory_id: int
    summary: str
    # pgvector 余弦距离，取值范围 [0, 2]，越小越相似。
    distance: float


@dataclass(slots=True)
class CreatedMemory:
    """成功写入数据库的记忆。"""

    memory_id: int
    memory_version_id: int
    memory_type: MemoryType
    summary: str


@dataclass(slots=True)
class DuplicatedMemory:
    """被判定为重复而放弃写入的记忆。"""

    summary: str
    # 命中的已有记忆 ID。大模型未能给出具体 ID 时为 None。
    duplicate_of_id: int | None
    reason: str


@dataclass(slots=True)
class PendingResplitMemory:
    """摘要散乱、需要重新拆分而被挂起的记忆。"""

    memory_type: MemoryType
    refined_content: str
    reason: str


@dataclass(slots=True)
class ExtractionReport:
    """
    一次提取的最终结果。

    刻意**不包含**被分类阶段丢弃的内容：按需求，不属于两类的信息
    直接丢弃且不做任何提示。
    """

    created: list[CreatedMemory] = field(default_factory=list)
    duplicated: list[DuplicatedMemory] = field(default_factory=list)
    pending_resplit: list[PendingResplitMemory] = field(default_factory=list)

    def render_text(self) -> str:
        """
        渲染成便于人工阅读的多行文本，供命令行入口输出。

        返回：
        - 中文多行报告字符串。三类结果都为空时给出明确提示，避免看起来像程序没跑。
        """
        lines: list[str] = []

        lines.append(
            f"新增记忆 {len(self.created)} 条 / "
            f"重复放弃 {len(self.duplicated)} 条 / "
            f"待重新拆分 {len(self.pending_resplit)} 条"
        )

        if self.created:
            lines.append("")
            lines.append("【新增】")
            for item in self.created:
                lines.append(
                    f"  #{item.memory_id} [{item.memory_type.label_zh}] {item.summary}"
                )

        if self.duplicated:
            lines.append("")
            lines.append("【重复放弃】")
            for item in self.duplicated:
                hit = f"命中 #{item.duplicate_of_id}" if item.duplicate_of_id else "命中已有记忆"
                lines.append(f"  {item.summary}（{hit}：{item.reason}）")

        if self.pending_resplit:
            lines.append("")
            lines.append("【待重新拆分】")
            for item in self.pending_resplit:
                lines.append(f"  [{item.memory_type.label_zh}] {item.reason}")
                lines.append(f"    正文：{item.refined_content}")

        if not (self.created or self.duplicated or self.pending_resplit):
            lines.append("")
            lines.append("本次未产生任何记忆：原文中没有可归入「个人信息」或「事件」的内容。")

        return "\n".join(lines)
