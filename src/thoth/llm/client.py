"""
大模型客户端封装。

职责：
1. 集中持有 OpenAI 客户端实例，避免业务代码到处 new client。
2. 提供 ``chat_structured()``：基于 Structured Outputs 直接拿到强类型的 Pydantic 对象。
3. 提供 ``embed()``：把文本转成向量，供 pgvector 检索使用。

设计取舍：
- 只暴露这两个方法。业务层不应该出现任何裸的 OpenAI SDK 调用，
  这样后续换模型、换网关、加重试或加缓存都只改这一个文件。
- 使用同步客户端。整条提取流水线是同步的，引入 async 只会增加复杂度而没有收益。
- 温度固定为 0。记忆提取要求结果稳定可复现，不需要创造性。
"""

from __future__ import annotations

from typing import TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from thoth.config import Settings, get_settings

# 结构化输出的目标类型，必须是 Pydantic 模型。
SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LlmError(RuntimeError):
    """
    大模型调用失败时抛出的统一异常。

    把 OpenAI SDK 的各种异常、以及「拒答」「解析结果为空」等
    业务上同样无法继续的情况都归一到这个类型，
    让上层只需要 catch 一种异常。
    """


class LlmClient:
    """
    对话模型与 Embedding 模型的统一入口。

    典型用法：

        client = LlmClient()
        result = client.chat_structured(
            system=prompts.CLASSIFY_SYSTEM,
            user="用户目前居住在大阪。",
            schema=ClassificationResult,
        )
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """
        入参：
        - settings : 运行期配置。为 None 时取全局单例配置。
        """
        self._settings = settings or get_settings()
        self._client = OpenAI(
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
        )

    @property
    def settings(self) -> Settings:
        """暴露配置，方便调用方读取模型名等信息用于日志。"""
        return self._settings

    def chat_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
    ) -> SchemaT:
        """
        调用对话模型并返回结构化结果。

        入参：
        - system : 系统提示词，描述任务与约束。
        - user   : 用户消息，通常是待处理的文本内容。
        - schema : 期望的输出结构（Pydantic 模型类）。

        返回：
        - 解析好的 ``schema`` 实例。

        异常：
        - LlmError：网络/鉴权失败、模型拒答、或响应无法解析成目标结构。
        """
        try:
            completion = self._client.chat.completions.parse(
                model=self._settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                temperature=0,
            )
        except OpenAIError as exc:
            raise LlmError(f"调用对话模型失败：{exc}") from exc

        message = completion.choices[0].message

        # 模型出于安全策略拒答时，parsed 为 None 但 refusal 有内容。
        if message.refusal:
            raise LlmError(f"对话模型拒绝处理该请求：{message.refusal}")

        if message.parsed is None:
            raise LlmError(
                f"对话模型未返回可解析的 {schema.__name__} 结构，原始内容：{message.content!r}"
            )

        return message.parsed

    def embed(self, text: str) -> list[float]:
        """
        把文本转换为向量。

        入参：
        - text : 待向量化的文本。本项目中固定传入记忆摘要，而非完整正文。

        返回：
        - 浮点数列表，长度等于配置的 ``embedding_dim``。

        异常：
        - ValueError：文本为空白。
        - LlmError  ：调用失败，或返回维度与配置不一致（说明模型配置与建表语句不匹配）。
        """
        normalized = text.strip()
        if not normalized:
            raise ValueError("待向量化的文本不能为空。")

        try:
            response = self._client.embeddings.create(
                model=self._settings.embedding_model,
                input=normalized,
            )
        except OpenAIError as exc:
            raise LlmError(f"调用 Embedding 模型失败：{exc}") from exc

        vector = response.data[0].embedding

        # 维度不一致会导致 pgvector 插入直接报错，这里提前拦住并给出可操作的提示。
        if len(vector) != self._settings.embedding_dim:
            raise LlmError(
                f"Embedding 维度不匹配：模型 {self._settings.embedding_model} "
                f"返回 {len(vector)} 维，但配置与建表语句要求 {self._settings.embedding_dim} 维。"
            )

        return list(vector)
