"""
记忆提取流水线：串起「产出记忆数据」与「查重落表」两个阶段。

完整链路：

    原始文本
      ↓ 阶段一（draft_builder，不碰数据库）
      粗提取 → 逐条分类 → 按类型精炼 → 生成摘要 → 记忆草稿
      ↓ 阶段二（本模块，需要数据库）
      摘要向量化 → 向量召回 → 大模型终裁 → 写入 memory + memory_version
      ↓
      ExtractionReport

两个阶段刻意分开：
- 阶段一由 ``MemoryDraftBuilder`` 负责，只需要大模型，不需要数据库，
  因此可以单独测试记忆的提取质量（见 tests/unit/test_draft_builder.py）；
- 阶段二由本模块负责，是唯一会真正写库的地方。

容错策略：
单条记忆落表失败不会中断整批。异常被捕获并记录日志后跳过该条，继续处理剩余记忆。
"""

from __future__ import annotations

import logging

import psycopg

from thoth.config import Settings, get_settings
from thoth.db.memory_repo import MemoryRepository
from thoth.extraction.deduplicator import MemoryDeduplicator
from thoth.extraction.draft_builder import DraftBatch, MemoryDraftBuilder
from thoth.llm.client import LlmClient
from thoth.models import (
    CreatedMemory,
    DuplicatedMemory,
    ExtractionReport,
    MemoryDraft,
)

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """
    记忆提取流水线。

    典型用法：

        with open_connection() as conn:
            pipeline = ExtractionPipeline.build(conn)
            report = pipeline.run(text)
            print(report.render_text())

    只想看提取效果、不想写库时，直接用 ``MemoryDraftBuilder`` 即可，
    不需要构造本类。
    """

    def __init__(
        self,
        *,
        draft_builder: MemoryDraftBuilder,
        deduplicator: MemoryDeduplicator,
        repository: MemoryRepository,
        settings: Settings,
    ) -> None:
        """
        入参：全部为已构造好的协作对象，便于单元测试逐个替换。
        常规使用请走 ``ExtractionPipeline.build()`` 工厂方法。
        """
        self._draft_builder = draft_builder
        self._deduplicator = deduplicator
        self._repository = repository
        self._settings = settings

    @classmethod
    def build(
        cls,
        connection: psycopg.Connection,
        settings: Settings | None = None,
    ) -> ExtractionPipeline:
        """
        按配置组装一条完整的流水线。

        入参：
        - connection : 已注册 pgvector 类型的数据库连接。
        - settings   : 运行期配置。为 None 时取全局单例配置。

        返回：
        - 装配完成的 ExtractionPipeline。
        """
        resolved = settings or get_settings()
        llm_client = LlmClient(resolved)
        repository = MemoryRepository(connection)

        return cls(
            draft_builder=MemoryDraftBuilder.build(llm_client),
            deduplicator=MemoryDeduplicator(llm_client, repository),
            repository=repository,
            settings=resolved,
        )

    def run(self, text: str) -> ExtractionReport:
        """
        对一段原始文本执行完整的提取流程，包含落表。

        入参：
        - text : 原始文本。

        返回：
        - ExtractionReport，包含新增、重复放弃、待重拆三类结果。
          被分类阶段丢弃的内容按需求不出现在结果里。

        异常：
        - ValueError：原始文本为空白。
        - LlmError  ：粗提取失败（这一步失败意味着整批无法继续，不做容错）。
        """
        batch = self._draft_builder.build_drafts(text)
        return self.persist_batch(batch)

    def persist_batch(self, batch: DraftBatch) -> ExtractionReport:
        """
        对一批已构建好的草稿执行查重与落表。

        入参：
        - batch : 草稿批次，通常来自 ``MemoryDraftBuilder.build_drafts()``。

        返回：
        - ExtractionReport。待重拆的记忆原样转入报告，不参与落表。

        单独暴露这个方法的用途：
        草稿可以先经人工审核，确认无误后再调用本方法落表；
        测试时也可以只跑阶段一而完全不触碰数据库。
        """
        report = ExtractionReport(pending_resplit=list(batch.pending_resplit))

        for index, draft in enumerate(batch.drafts, start=1):
            try:
                self._persist_one(draft, report)
            except Exception:
                # 单条失败不影响整批。用 exception 记录完整堆栈，便于事后定位。
                logger.exception(
                    "第 %d/%d 条草稿落表失败，已跳过。摘要：%s",
                    index,
                    len(batch.drafts),
                    draft.summary,
                )

        logger.info(
            "提取完成：新增 %d 条，重复放弃 %d 条，待重拆 %d 条。",
            len(report.created),
            len(report.duplicated),
            len(report.pending_resplit),
        )
        return report

    def _persist_one(self, draft: MemoryDraft, report: ExtractionReport) -> None:
        """
        对单条草稿执行查重与落表，并把结果登记到报告中。

        入参：
        - draft  : 一条记忆草稿。
        - report : 累积结果的报告对象，本方法会就地修改它。

        异常：
        - 向上抛出查重与写库的异常，由 ``persist_batch()`` 统一捕获并跳过该条。
        """
        # 步骤 5-7：摘要向量化 + 向量召回 + 大模型终裁。
        dedup_outcome = self._deduplicator.check(draft.summary)

        if dedup_outcome.is_duplicate:
            logger.info("摘要与已有记忆重复，放弃写入：%s", draft.summary)
            report.duplicated.append(
                DuplicatedMemory(
                    summary=draft.summary,
                    duplicate_of_id=dedup_outcome.duplicate_of_id,
                    reason=dedup_outcome.reason or "模型判定与已有记忆表达同一事实。",
                )
            )
            return

        # 步骤 8：写库。复用查重阶段已经算好的向量，不再重复调用 Embedding 接口。
        memory_id, version_id = self._repository.create_memory(
            summary=draft.summary,
            embedding=dedup_outcome.embedding,
            content=draft.refined_content,
            operator=self._settings.operator,
        )

        logger.info(
            "已写入记忆 #%d（%s）：%s",
            memory_id,
            draft.memory_type.value,
            draft.summary,
        )
        report.created.append(
            CreatedMemory(
                memory_id=memory_id,
                memory_version_id=version_id,
                memory_type=draft.memory_type,
                summary=draft.summary,
            )
        )

    def _resplit(self, draft: MemoryDraft) -> list[MemoryDraft]:
        """
        重新拆分一条过于散乱的记忆。

        当前版本刻意不实现，只保留接口占位。等需要补齐时，
        在这里实现「把一条混合主题的记忆再拆成多条」的逻辑，
        并把 ``MemoryDraftBuilder._build_one`` 中挂起 pending_resplit 的分支
        改为调用本方法即可，流水线的其他部分不需要改动。

        入参：
        - draft : 被判定为散乱的记忆中间态。

        返回：
        - 重新拆分后的多条记忆中间态。

        异常：
        - NotImplementedError：始终抛出。
        """
        raise NotImplementedError(
            "记忆重新拆分功能尚未实现。当前散乱的记忆会被挂起并在 ExtractionReport "
            "的 pending_resplit 中报告，不会写入数据库。"
        )
