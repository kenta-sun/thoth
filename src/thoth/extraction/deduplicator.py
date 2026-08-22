"""
记忆查重器：流水线的第五到第七步。

流程：
1. 把摘要向量化（只用摘要，不用正文）。
2. 用向量在库里召回 Top-K 条最相似的 ACTIVE 记忆。
3. 按余弦距离阈值过滤候选；没有候选剩下就直接判为新记忆，不消耗大模型调用。
4. 剩下的候选交给大模型做语义终裁，由它决定是否真的重复。

核心设计原则：**向量距离只用来找候选，不用来下结论**。
距离近只代表用词接近，不代表事实相同（例如「用户住在东京」与「用户住在大阪」
距离极近，但这是信息发生了变化，绝不是重复）。因此最终判定必须交给大模型。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from thoth.db.memory_repo import MemoryRepository
from thoth.llm import prompts
from thoth.llm.client import LlmClient
from thoth.models import CandidateMemory, DuplicateJudgement

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DedupOutcome:
    """
    查重结果。

    字段：
    - embedding       : 摘要向量。判定为不重复时，流水线会直接复用它写库，
                        避免为同一条摘要重复调用一次 Embedding 接口。
    - is_duplicate    : 是否与已有记忆重复。
    - duplicate_of_id : 重复时命中的已有记忆 ID；不重复时为 None。
    - reason          : 判定理由，用于结果报告与人工复核。
    """

    embedding: list[float]
    is_duplicate: bool
    duplicate_of_id: int | None
    reason: str


class MemoryDeduplicator:
    """摘要级查重器。"""

    def __init__(
        self,
        llm_client: LlmClient,
        repository: MemoryRepository,
    ) -> None:
        """
        入参：
        - llm_client : 大模型客户端，用于生成摘要向量与执行语义终裁。
        - repository : 记忆仓储，用于向量召回。
        """
        self._llm = llm_client
        self._repository = repository
        settings = llm_client.settings
        self._top_k = settings.dedup_top_k
        self._max_distance = settings.dedup_max_distance

    def check(self, summary: str) -> DedupOutcome:
        """
        判断一条摘要是否与库中已有记忆重复。

        入参：
        - summary : 待写入记忆的摘要。

        返回：
        - DedupOutcome。无论是否重复，embedding 字段都已填好。

        异常：
        - ValueError    ：摘要为空白。
        - LlmError      ：Embedding 或对话模型调用失败。
        - DatabaseError ：向量召回失败。
        """
        normalized = summary.strip()
        if not normalized:
            raise ValueError("待查重的摘要不能为空。")

        # 步骤 5：摘要向量化。
        embedding = self._llm.embed(normalized)

        # 步骤 6：向量召回候选。
        raw_candidates = self._repository.search_similar_by_embedding(
            embedding=embedding,
            top_k=self._top_k,
        )
        candidates = self._filter_by_distance(raw_candidates)

        # 阈值内没有任何候选，说明库里不存在语义接近的记忆，
        # 直接判为新记忆，省掉一次大模型调用。
        if not candidates:
            logger.debug("无阈值内候选，直接判为新记忆：%s", normalized)
            return DedupOutcome(
                embedding=embedding,
                is_duplicate=False,
                duplicate_of_id=None,
                reason="向量召回未找到语义接近的已有记忆。",
            )

        # 步骤 7：大模型语义终裁。
        judgement = self._llm.chat_structured(
            system=prompts.DEDUP_JUDGE_SYSTEM,
            user=prompts.build_dedup_judge_user(normalized, candidates),
            schema=DuplicateJudgement,
        )

        return DedupOutcome(
            embedding=embedding,
            is_duplicate=judgement.is_duplicate,
            duplicate_of_id=self._resolve_duplicate_id(judgement, candidates),
            reason=judgement.reason.strip(),
        )

    def _filter_by_distance(
        self,
        candidates: list[CandidateMemory],
    ) -> list[CandidateMemory]:
        """
        按余弦距离阈值过滤候选。

        入参：
        - candidates : 向量召回的原始候选列表。

        返回：
        - 距离不超过阈值的候选列表。

        说明：向量索引召回的是「最近的 K 条」，即使全库都毫不相关也会返回结果。
        这里用阈值把明显不相关的候选剔掉，既减少大模型的干扰项，也省下调用成本。
        """
        kept = [item for item in candidates if item.distance <= self._max_distance]

        dropped = len(candidates) - len(kept)
        if dropped:
            logger.debug(
                "按距离阈值 %.3f 过滤掉 %d 条候选，保留 %d 条。",
                self._max_distance,
                dropped,
                len(kept),
            )

        return kept

    @staticmethod
    def _resolve_duplicate_id(
        judgement: DuplicateJudgement,
        candidates: list[CandidateMemory],
    ) -> int | None:
        """
        校正大模型给出的重复记忆 ID。

        入参：
        - judgement  : 大模型的判定结果。
        - candidates : 本次提供给模型的候选列表。

        返回：
        - 校验通过的候选记忆 ID；判定为不重复、或模型给出的 ID 不在候选列表中时返回 None。

        存在的必要性：模型偶尔会臆造一个不在候选里的 ID。
        这种 ID 一旦进入结果报告会误导人工复核，因此必须校验后再采用。
        """
        if not judgement.is_duplicate:
            return None

        if judgement.duplicate_of_id is None:
            return None

        valid_ids = {item.memory_id for item in candidates}
        if judgement.duplicate_of_id not in valid_ids:
            logger.warning(
                "模型返回的重复记忆 ID %d 不在候选列表 %s 中，已忽略该 ID。",
                judgement.duplicate_of_id,
                sorted(valid_ids),
            )
            return None

        return judgement.duplicate_of_id
