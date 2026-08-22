"""
记忆摘要生成器：流水线的第四步。

职责：
1. 为精炼后的记忆正文生成 100 字以内的摘要。
2. 判断这条记忆是否过于散乱（说明上游拆分得不好），并把信号传给流水线。
3. 对摘要长度做硬校验，保证一定能写进 memory.summary 这个 VARCHAR(128) 列。

长度处理策略（三层兜底）：
- 第一层：提示词里写明字符数上限。
- 第二层：超长时带着「上一次的失败结果」重试一次，成功率远高于原样重试。
- 第三层：重试仍超长则直接截断并记 warning。宁可摘要不完美，也不能让整条记忆写不进去。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from thoth.llm import prompts
from thoth.llm.client import LlmClient
from thoth.models import SummaryResult

logger = logging.getLogger(__name__)

# memory.summary 列宽（VARCHAR(128)）。截断时的绝对上限，
# 与配置项 summary_max_chars（默认 100）取更小值，双重保险。
SUMMARY_COLUMN_LIMIT = 128


@dataclass(slots=True)
class SummaryOutcome:
    """
    摘要生成结果。

    字段：
    - summary        : 最终可用的摘要，已保证长度合规。
    - needs_resplit  : 该条记忆是否过于散乱、需要重新拆分。
    - resplit_reason : 需要重拆的原因；不需要时为空字符串。
    """

    summary: str
    needs_resplit: bool
    resplit_reason: str


class MemorySummarizer:
    """摘要生成器。"""

    def __init__(self, llm_client: LlmClient) -> None:
        """
        入参：
        - llm_client : 大模型客户端。摘要长度上限从其配置中读取。
        """
        self._llm = llm_client
        # 取配置值与列宽的较小者，避免有人把配置调到超过列宽导致插入失败。
        self._max_chars = min(
            llm_client.settings.summary_max_chars,
            SUMMARY_COLUMN_LIMIT,
        )

    def summarize(self, refined_content: str) -> SummaryOutcome:
        """
        为记忆正文生成摘要。

        入参：
        - refined_content : 精炼后的记忆正文。

        返回：
        - SummaryOutcome。其中 summary 一定非空且长度不超过上限。

        异常：
        - ValueError：正文为空白，或模型两次都返回了空摘要。
        - LlmError  ：大模型调用失败。
        """
        normalized = refined_content.strip()
        if not normalized:
            raise ValueError("待生成摘要的记忆正文不能为空。")

        system_prompt = prompts.build_summarize_system(self._max_chars)

        first = self._llm.chat_structured(
            system=system_prompt,
            user=prompts.build_summarize_user(normalized),
            schema=SummaryResult,
        )

        summary = first.summary.strip()
        if not summary:
            raise ValueError(f"模型返回了空摘要，记忆正文：{normalized!r}")

        # 第二层兜底：超长时带着失败信息重试一次。
        if len(summary) > self._max_chars:
            logger.info(
                "摘要超长（%d > %d），带反馈重试一次。", len(summary), self._max_chars
            )
            retried = self._llm.chat_structured(
                system=system_prompt,
                user=prompts.build_summarize_retry_user(
                    refined_content=normalized,
                    previous_summary=summary,
                    max_chars=self._max_chars,
                ),
                schema=SummaryResult,
            )
            retried_summary = retried.summary.strip()
            if retried_summary:
                summary = retried_summary

        # 第三层兜底：仍然超长则截断，保证数据一定写得进去。
        if len(summary) > self._max_chars:
            logger.warning(
                "重试后摘要仍超长（%d > %d），已截断。原摘要：%s",
                len(summary),
                self._max_chars,
                summary,
            )
            summary = summary[: self._max_chars]

        # 散乱标记只取第一次的判定：重试的目的仅是压缩长度，
        # 重试消息里没有完整的散乱判定语境，其结论不足以覆盖首次判断。
        return SummaryOutcome(
            summary=summary,
            needs_resplit=first.needs_resplit,
            resplit_reason=first.resplit_reason.strip(),
        )
