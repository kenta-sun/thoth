"""
记忆提取器：负责流水线的前三步。

1. **粗提取**：把一整段原始文本切成一条条粗记忆，只保留「个人信息」与「事件」相关的内容，
   允许啰嗦，重点是不丢信息。
2. **分类**：对每条粗记忆判定 PERSONAL / EVENT / DROP。判为 DROP 的直接丢弃，
   不入库、不进入返回结果、不做任何提示。
3. **精炼**：按类型选择对应的提示词，把粗记忆改写成逻辑严谨、无冗余的记忆正文。

三步各自独立调用一次大模型，刻意不合并成一次调用。原因是分类与精炼的
提示词要求差异很大，分开做每一步的指令都更聚焦，产出质量比一次性完成更稳定。
"""

from __future__ import annotations

import logging

from thoth.llm import prompts
from thoth.llm.client import LlmClient
from thoth.models import (
    ClassificationResult,
    CoarseExtractionResult,
    MemoryType,
    RefinementResult,
)

logger = logging.getLogger(__name__)


class MemoryExtractor:
    """
    粗提取 + 分类 + 精炼。

    产出的是「已精炼但还没有摘要」的中间结果，摘要与查重由后续步骤负责。
    """

    def __init__(self, llm_client: LlmClient) -> None:
        """
        入参：
        - llm_client : 大模型客户端。由外部注入，便于测试时替换成假实现。
        """
        self._llm = llm_client

    def extract_coarse_memories(self, text: str) -> list[str]:
        """
        步骤 1：从原始文本中粗提取记忆片段。

        入参：
        - text : 原始文本。

        返回：
        - 粗记忆字符串列表。原文中没有可记录内容时返回空列表。

        异常：
        - ValueError：原始文本为空白。
        - LlmError  ：大模型调用失败。
        """
        normalized = text.strip()
        if not normalized:
            raise ValueError("待提取的原始文本不能为空。")

        result = self._llm.chat_structured(
            system=prompts.EXTRACT_SYSTEM,
            user=prompts.build_extract_user(normalized),
            schema=CoarseExtractionResult,
        )

        # 模型偶尔会返回空字符串或纯空白项，这里统一清洗掉，避免污染后续步骤。
        coarse_memories = [item.strip() for item in result.memories if item.strip()]

        logger.info("粗提取完成：得到 %d 条粗记忆。", len(coarse_memories))
        return coarse_memories

    def classify(self, coarse_memory: str) -> MemoryType | None:
        """
        步骤 2：判定一条粗记忆的类型。

        入参：
        - coarse_memory : 一条粗记忆。

        返回：
        - PERSONAL 或 EVENT 对应的 MemoryType；
        - 判定为 DROP（不属于这两类）时返回 None，调用方应直接跳过该条。

        异常：
        - LlmError：大模型调用失败。
        """
        result = self._llm.chat_structured(
            system=prompts.CLASSIFY_SYSTEM,
            user=prompts.build_classify_user(coarse_memory),
            schema=ClassificationResult,
        )

        memory_type = result.label.to_memory_type()

        if memory_type is None:
            # 丢弃项按需求不对外提示，只记 debug 级日志，便于本地调优提示词。
            logger.debug("分类判定为 DROP，已丢弃：%s（理由：%s）", coarse_memory, result.reason)
        else:
            logger.debug("分类判定为 %s：%s", memory_type.value, coarse_memory)

        return memory_type

    def refine(self, coarse_memory: str, memory_type: MemoryType) -> str:
        """
        步骤 3：按类型精炼记忆正文。

        入参：
        - coarse_memory : 一条粗记忆。
        - memory_type   : 分类阶段判定出的类型，决定使用哪套精炼提示词。

        返回：
        - 精炼后的记忆正文。

        异常：
        - ValueError：类型没有登记对应的精炼提示词，或模型返回了空正文。
        - LlmError  ：大模型调用失败。
        """
        system_prompt = prompts.REFINE_SYSTEM_BY_TYPE.get(memory_type)
        if system_prompt is None:
            raise ValueError(
                f"记忆类型 {memory_type.value} 没有登记对应的精炼提示词，"
                "请在 prompts.REFINE_SYSTEM_BY_TYPE 中补充。"
            )

        result = self._llm.chat_structured(
            system=system_prompt,
            user=prompts.build_refine_user(coarse_memory),
            schema=RefinementResult,
        )

        refined = result.content.strip()
        if not refined:
            raise ValueError(f"精炼后的记忆正文为空，原始粗记忆：{coarse_memory!r}")

        return refined
