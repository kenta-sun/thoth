"""统计 DTO 层：承载计数及清零工具的请求及逐项结果，不混入数据库实体。"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class WordListItem:
    """承载一个解析后的原始元素，下标及原始值不在后续处理中修改。"""

    index: int  # 原 JSON 数组的零基下标，过滤和分组后保持不变。
    original_value: Any  # 原始输入值，可能是无效类型，仅供内部预处理使用。


@dataclass(frozen=True, slots=True)
class StatsResult:
    """承载提交后的统计结果或未执行原因。"""

    index: int  # 输入数组零基下标。
    word: str | None  # 原始单词；无法安全输出时为 None。
    status: Literal["updated", "skipped", "failed"]  # 成功、无需执行或失败。
    reason: str | None = None  # 跳过或失败原因；成功时省略。
    miss_count: int | None = None  # 本次操作后的值；未操作或不存在时省略。
    usage_count: int | None = None  # 本次操作后的值；未操作时省略。


@dataclass(frozen=True, slots=True)
class WordListPreprocessResult:
    """承载原始对象以及分离的待处理请求和跳过结果。"""

    original_items: list[WordListItem] = field(default_factory=list)  # 原序全部元素；整批终止时为空。
    pending_items: list[WordListItem] = field(default_factory=list)  # 有效且去重的项，引用原始对象。
    skipped_results: list[StatsResult] = field(default_factory=list)  # 已跳过项，保留原下标及原因。
