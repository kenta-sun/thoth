"""
LLM 子包：统一封装大语言模型调用与提示词。

对外暴露：
- ``LlmClient``：结构化对话 + 文本向量化的统一客户端。
- ``prompts``  ：各处理阶段使用的系统提示词常量。
"""

from thoth.llm.client import LlmClient

__all__ = ["LlmClient"]
