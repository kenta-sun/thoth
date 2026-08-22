"""
记忆草稿构建器：负责「产出记忆数据」这一整个阶段。

覆盖流水线的步骤 1-4：

    原始文本 → 粗提取 → 逐条分类 → 按类型精炼 → 生成摘要 → 记忆草稿

**本模块刻意不依赖数据库。** 只要给一个大模型客户端就能完整运行，
因此可以在没有 PostgreSQL 的环境里单独测试记忆的提取质量。

与 pipeline 的分工：
- 本模块只产出「可以写库的记忆数据」，不做任何查重与写库；
- ``ExtractionPipeline`` 拿到草稿之后才去连数据库做查重与落表。

这样切分的好处是：调提示词、看提取效果这类工作占了实际开发的大部分时间，
而这些工作完全不需要数据库参与。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from thoth.extraction.extractor import MemoryExtractor
from thoth.extraction.summarizer import MemorySummarizer
from thoth.llm.client import LlmClient
from thoth.models import MemoryDraft, PendingResplitMemory

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DraftBatch:
    """
    一次草稿构建的产出。

    字段：
    - drafts          : 已经带好摘要、可以进入查重与落表环节的记忆草稿。
    - pending_resplit : 摘要判定为散乱、需要重新拆分而被挂起的记忆。这些不会进入落表环节。

    被分类阶段判为 DROP 的内容不出现在任何字段里——按需求直接丢弃，不做提示。
    """

    drafts: list[MemoryDraft] = field(default_factory=list)
    pending_resplit: list[PendingResplitMemory] = field(default_factory=list)

    def render_text(self) -> str:
        """
        渲染成便于人工阅读的多行文本。

        返回：
        - 中文多行报告字符串，逐条列出草稿的类型、摘要、正文与原始片段。

        主要用于单元测试与提示词调优时直接观察产出，不参与生产逻辑。
        """
        lines: list[str] = [
            f"记忆草稿 {len(self.drafts)} 条 / 待重新拆分 {len(self.pending_resplit)} 条"
        ]

        for index, draft in enumerate(self.drafts, start=1):
            lines.append("")
            lines.append(f"[草稿 {index}] 类型：{draft.memory_type.label_zh}")
            lines.append(f"  摘要（{len(draft.summary)} 字）：{draft.summary}")
            lines.append(f"  正文：{draft.refined_content}")
            lines.append(f"  原始片段：{draft.raw_content}")

        for index, pending in enumerate(self.pending_resplit, start=1):
            lines.append("")
            lines.append(f"[待重拆 {index}] 类型：{pending.memory_type.label_zh}")
            lines.append(f"  原因：{pending.reason}")
            lines.append(f"  正文：{pending.refined_content}")

        if not (self.drafts or self.pending_resplit):
            lines.append("")
            lines.append("没有产出任何草稿：原文中没有可归入「个人信息」或「事件」的内容。")

        return "\n".join(lines)


class MemoryDraftBuilder:
    """
    把原始文本转换成一批记忆草稿。

    典型用法：

        builder = MemoryDraftBuilder.build(LlmClient())
        batch = builder.build_drafts("我目前住在大阪。")
        print(batch.render_text())
    """

    def __init__(
        self,
        extractor: MemoryExtractor,
        summarizer: MemorySummarizer,
    ) -> None:
        """
        入参：
        - extractor  : 负责粗提取、分类、精炼。
        - summarizer : 负责摘要与散乱检测。
        """
        self._extractor = extractor
        self._summarizer = summarizer

    @classmethod
    def build(cls, llm_client: LlmClient) -> MemoryDraftBuilder:
        """
        用一个大模型客户端组装出构建器。

        入参：
        - llm_client : 大模型客户端。

        返回：
        - 装配完成的 MemoryDraftBuilder。
        """
        return cls(
            extractor=MemoryExtractor(llm_client),
            summarizer=MemorySummarizer(llm_client),
        )

    def build_drafts(self, text: str) -> DraftBatch:
        """
        对一段原始文本执行步骤 1-4，产出记忆草稿。

        入参：
        - text : 原始文本。

        返回：
        - DraftBatch。原文中没有可记录内容时返回空批次。

        异常：
        - ValueError：原始文本为空白。
        - LlmError  ：粗提取失败。这一步失败意味着整批无法继续，因此不做容错。

        容错策略：
        粗提取之后，单条记忆处理失败不会中断整批——异常记录堆栈后跳过该条，
        继续处理剩余记忆。一次提取通常涉及几十条，
        让一条脏数据毁掉整批的代价远大于收益。
        """
        batch = DraftBatch()

        coarse_memories = self._extractor.extract_coarse_memories(text)
        if not coarse_memories:
            logger.info("原文中没有可归入「个人信息」或「事件」的内容，本次不产生任何记忆。")
            return batch

        for index, coarse_memory in enumerate(coarse_memories, start=1):
            try:
                self._build_one(coarse_memory, batch)
            except Exception:
                logger.exception(
                    "第 %d/%d 条记忆构建失败，已跳过。粗记忆内容：%s",
                    index,
                    len(coarse_memories),
                    coarse_memory,
                )

        logger.info(
            "草稿构建完成：可落表 %d 条，待重拆 %d 条。",
            len(batch.drafts),
            len(batch.pending_resplit),
        )
        return batch

    def _build_one(self, coarse_memory: str, batch: DraftBatch) -> None:
        """
        把单条粗记忆构建成草稿，并登记到批次中。

        入参：
        - coarse_memory : 一条粗记忆。
        - batch         : 累积产出的批次对象，本方法会就地修改它。

        异常：
        - 向上抛出各步骤的异常，由 ``build_drafts()`` 统一捕获并跳过该条。
        """
        # 步骤 2：分类。判为 DROP 的直接返回，不入批次、不做提示。
        memory_type = self._extractor.classify(coarse_memory)
        if memory_type is None:
            return

        # 步骤 3：按类型精炼。
        refined_content = self._extractor.refine(coarse_memory, memory_type)

        # 步骤 4：生成摘要。
        summary_outcome = self._summarizer.summarize(refined_content)

        # 摘要散乱说明上游拆分得不好。当前不实现重拆，先挂起。
        if summary_outcome.needs_resplit:
            logger.info(
                "记忆过于散乱，已挂起等待重新拆分：%s", summary_outcome.resplit_reason
            )
            batch.pending_resplit.append(
                PendingResplitMemory(
                    memory_type=memory_type,
                    refined_content=refined_content,
                    reason=summary_outcome.resplit_reason or "模型判定该条记忆主题混杂。",
                )
            )
            return

        batch.drafts.append(
            MemoryDraft(
                raw_content=coarse_memory,
                memory_type=memory_type,
                refined_content=refined_content,
                summary=summary_outcome.summary,
            )
        )
