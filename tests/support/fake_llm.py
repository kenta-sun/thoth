"""
假的大模型客户端，供单元测试替换真实的 ``LlmClient``。

为什么需要它：
- 真实调用要花钱、要联网，而且模型输出不确定，没法写稳定断言；
- 我们真正想测的是**流水线的编排逻辑**（分类结果如何分流、精炼选了哪套提示词、
  摘要超长如何压回、散乱如何挂起），这些都不需要真实模型参与。

用法上是「脚本化」的：测试预先声明「模型会怎么回答」，
本类按调用时传入的 schema 与提示词内容把对应答案取出来返回，
同时把每次调用记录下来供断言。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thoth.config import Settings
from thoth.llm import prompts
from thoth.models import (
    ClassificationLabel,
    ClassificationResult,
    CoarseExtractionResult,
    MemoryType,
    RefinementResult,
    SummaryResult,
)


def build_test_settings(**overrides) -> Settings:
    """
    构造一份测试用配置。

    入参：
    - overrides : 需要覆盖的字段，例如 ``summary_max_chars=20``。

    返回：
    - Settings 实例。

    存在的必要性：真实的 ``get_settings()`` 会读 .env 并强制要求 OPENAI_API_KEY，
    测试不该依赖本机环境，所以这里直接把字段写死。
    数据库相关字段填的是明显无效的值，一旦有代码试图真的连库会立刻失败，
    正好能暴露「本该不碰数据库的逻辑却碰了数据库」这类问题。
    """
    defaults = {
        "openai_api_key": "fake-key-for-test",
        "openai_base_url": None,
        "llm_model": "fake-llm",
        "embedding_model": "fake-embedding",
        "embedding_dim": 8,
        "pg_dsn": "postgresql://invalid-host-on-purpose/none",
        "dedup_top_k": 5,
        "dedup_max_distance": 0.35,
        "operator": "UNIT_TEST",
        "summary_max_chars": 100,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _extract_block(message: str, tag: str) -> str:
    """
    从提示词的用户消息中取出被指定标签包裹的正文。

    入参：
    - message : 用户消息全文。
    - tag     : 标签名，例如 ``粗记忆``。

    返回：
    - 标签内的正文，已去除首尾空白。

    异常：
    - AssertionError：消息里找不到该标签。说明提示词构造函数的格式变了，
      此时应当同步更新本文件，而不是让测试静默走到错误分支。
    """
    opening = f"<{tag}>"
    closing = f"</{tag}>"

    assert opening in message and closing in message, (
        f"用户消息里找不到 <{tag}> 标签，提示词格式可能已变更。消息内容：{message!r}"
    )

    return message.split(opening, 1)[1].split(closing, 1)[0].strip()


@dataclass
class RefineCall:
    """记录一次精炼调用，用于断言「按类型选对了提示词」。"""

    coarse_memory: str
    # 从系统提示词反推出的类型。识别不出时为 None。
    detected_type: MemoryType | None


class FakeLlmClient:
    """
    脚本化的假大模型客户端。

    构造参数：
    - settings        : 配置。摘要器会从这里读 ``summary_max_chars``。
    - coarse_memories : 粗提取阶段固定返回的粗记忆列表。
    - classifications : 粗记忆 → 分类标签。
    - refinements     : 粗记忆 → 精炼后的正文。
    - summaries       : 精炼正文 → 摘要结果队列。队列支持多个元素，
                        用于模拟「首次超长、重试后合规」这种多轮场景；
                        队列耗尽后会一直返回最后一个元素。

    ``embed`` 与判重相关调用一律直接失败。这批测试只覆盖到落表之前，
    一旦走到向量化或判重就说明阶段划分被破坏了，应该立刻暴露出来。
    """

    def __init__(
        self,
        *,
        settings: Settings,
        coarse_memories: list[str],
        classifications: dict[str, ClassificationLabel],
        refinements: dict[str, str],
        summaries: dict[str, list[SummaryResult]],
    ) -> None:
        self.settings = settings
        self._coarse_memories = coarse_memories
        self._classifications = classifications
        self._refinements = refinements
        # 复制一份，避免测试之间互相污染队列状态。
        self._summaries = {key: list(value) for key, value in summaries.items()}

        # ---------- 调用记录，供测试断言 ----------
        self.extract_call_count = 0
        self.classified: list[str] = []
        self.refine_calls: list[RefineCall] = []
        self.summarize_call_count = 0

    # ------------------------------------------------------------
    # LlmClient 的公开接口
    # ------------------------------------------------------------

    def chat_structured(self, *, system: str, user: str, schema):
        """按 schema 分派到对应的假答案。"""
        if schema is CoarseExtractionResult:
            return self._do_extract(system)

        if schema is ClassificationResult:
            return self._do_classify(user)

        if schema is RefinementResult:
            return self._do_refine(system, user)

        if schema is SummaryResult:
            return self._do_summarize(system, user)

        raise AssertionError(
            f"测试用假客户端收到了未预期的 schema：{schema}。"
            "这批测试只覆盖到落表之前，不应触发判重相关调用。"
        )

    def embed(self, text: str) -> list[float]:
        """向量化。这批测试不该走到这里。"""
        raise AssertionError(
            f"测试用假客户端不应被调用 embed()，说明代码在落表之前就做了向量化。文本：{text!r}"
        )

    # ------------------------------------------------------------
    # 各阶段的假实现
    # ------------------------------------------------------------

    def _do_extract(self, system: str) -> CoarseExtractionResult:
        assert system is prompts.EXTRACT_SYSTEM, "粗提取用错了系统提示词。"
        self.extract_call_count += 1
        return CoarseExtractionResult(memories=list(self._coarse_memories))

    def _do_classify(self, user: str) -> ClassificationResult:
        coarse_memory = _extract_block(user, "粗记忆")
        self.classified.append(coarse_memory)

        assert coarse_memory in self._classifications, (
            f"测试没有为这条粗记忆声明分类结果：{coarse_memory!r}"
        )
        label = self._classifications[coarse_memory]
        return ClassificationResult(label=label, reason=f"测试固定判定为 {label.value}")

    def _do_refine(self, system: str, user: str) -> RefinementResult:
        coarse_memory = _extract_block(user, "粗记忆")

        # 反查系统提示词属于哪个类型，让测试能验证「按类型选对了提示词」。
        detected_type: MemoryType | None = None
        for memory_type, refine_system in prompts.REFINE_SYSTEM_BY_TYPE.items():
            if system is refine_system:
                detected_type = memory_type
                break

        self.refine_calls.append(
            RefineCall(coarse_memory=coarse_memory, detected_type=detected_type)
        )

        assert coarse_memory in self._refinements, (
            f"测试没有为这条粗记忆声明精炼结果：{coarse_memory!r}"
        )
        return RefinementResult(content=self._refinements[coarse_memory])

    def _do_summarize(self, system: str, user: str) -> SummaryResult:
        assert f"{self.settings.summary_max_chars} 个字符" in system, (
            "摘要系统提示词里没有正确填入字符数上限。"
        )

        refined_content = _extract_block(user, "记忆正文")
        self.summarize_call_count += 1

        assert refined_content in self._summaries, (
            f"测试没有为这条正文声明摘要结果：{refined_content!r}"
        )

        queue = self._summaries[refined_content]
        # 队列里还剩多个时逐个消费，只剩一个时固定返回它，
        # 这样「首次超长 → 重试合规」和「一次到位」两种场景都能用同一套数据表达。
        return queue.pop(0) if len(queue) > 1 else queue[0]
