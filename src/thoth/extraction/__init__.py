"""
记忆提取子包：把一段原始文本转换成一条条可入库的长期记忆。

分成两个阶段，界限就是「是否需要数据库」：

阶段一——产出记忆数据（不碰数据库）
1. ``extractor``     ：粗提取 → 严格分类 → 按类型精炼。
2. ``summarizer``    ：生成 100 字以内摘要，并检测记忆是否过于散乱。
3. ``draft_builder`` ：把上面两步串成 ``原始文本 → 记忆草稿``。

阶段二——查重与落表（需要数据库）
4. ``deduplicator``  ：摘要向量化 → 向量召回候选 → 由大模型终裁是否重复。
5. ``pipeline``      ：串起两个阶段，并负责写库与汇总结果。
"""

from thoth.extraction.draft_builder import DraftBatch, MemoryDraftBuilder
from thoth.extraction.pipeline import ExtractionPipeline

__all__ = ["DraftBatch", "ExtractionPipeline", "MemoryDraftBuilder"]
