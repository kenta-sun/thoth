"""
记忆提取的手动验证脚本（以 pytest 用例的形式承载）。

测试范围：**只测到落表之前**，即只覆盖 ``MemoryDraftBuilder``：
粗提取 → 分类 → 按类型精炼 → 生成摘要。
查重与写库属于 ``ExtractionPipeline`` 的另一个阶段，不在本文件范围内。

与早期版本的关键区别：
1. 原始文本不再写死在代码里，而是从 ``tests/fixtures`` 目录下的纯文本文件读取，
   这样可以放真实、完整的一段笔记进去，而不是几句摘出来的短句。
2. 真实调用大模型（``LlmClient``，读取项目根目录 ``.env`` 里的配置），
   不再用脚本化的假客户端。因为我们想看的是提示词在真实模型上的实际效果，
   而不是「重放一遍自己写的预期答案」。
3. 不做任何 ``assert``。这里只负责跑通流水线并把结果完整打印到控制台，
   对错由人工看输出自行判断。pyproject 里已经配了 ``-s``，直接 ``pytest`` 就能看到。

因此这两个用例都会联网、消耗真实的 API 调用额度，运行前请确认 ``.env``
里的 ``OPENAI_API_KEY`` 等配置已经就绪。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from thoth.config import get_settings
from thoth.extraction.draft_builder import MemoryDraftBuilder
from thoth.llm.client import LlmClient

# tests/fixtures 目录：存放原始文本素材，与本文件所在的 tests/unit 平级。
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _read_fixture(filename: str) -> str:
    """
    读取 fixtures 目录下的一个纯文本文件作为原始文本。

    入参：
    - filename : 文件名，例如 ``mixed_personal_event_tech.md``。
    返回：
    - 文件的完整文本内容。
    """
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


def _print_section(title: str, body: str) -> None:
    """把一段内容以带标题的形式打到控制台，方便人工翻阅。"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)
    print(body)
    print("=" * 70)


# ============================================================
# 用例一：常规场景——一段混合了个人信息、事件与技术知识的笔记
# ============================================================


def test_混合文本只保留个人信息与事件():
    """
    读取 ``mixed_personal_event_tech.md``，跑一遍完整的草稿构建流程并打印结果。

    这段素材里混了个人信息、一次面试事件、一条纯技术知识，以及一句无信息量的闲聊。
    理想情况下技术知识与闲聊会被分类阶段判为 DROP，不出现在最终产出里；
    个人信息与事件应该各自走对精炼提示词。具体是否符合预期，靠打印出来的
    ``batch.render_text()`` 人工核对。
    """
    原始文本 = _read_fixture("mixed_personal_event_tech.md")

    llm_client = LlmClient(get_settings())
    builder = MemoryDraftBuilder.build(llm_client)

    batch = builder.build_drafts(原始文本)

    _print_section("用例一：混合文本，只保留个人信息与事件", batch.render_text())


# ============================================================
# 用例二：边界场景——话题分散的笔记 + 压低摘要字符上限
# ============================================================


def test_摘要超长会被压回上限且散乱记忆被挂起():
    """
    读取 ``scattered_life_notes.md``，并把摘要字符上限压到 20，
    人为制造「摘要容易超长」的场景，同时这段素材本身混了住地、语言学习、
    技术研究等多个互不相关的话题，观察摘要器是否会把它判为散乱并挂起。

    真实模型的判断存在不确定性，这里不对结果做任何断言，只把
    ``batch.render_text()`` 打印出来，超长重试、截断、挂起是否发生，
    都靠人工看控制台输出与上面的 DEBUG/INFO/WARNING 日志自行判断。
    """
    原始文本 = _read_fixture("scattered_life_notes.md")

    # frozen dataclass 不能直接改字段，用 dataclasses.replace 派生一份新配置。
    压低上限的配置 = dataclasses.replace(get_settings(), summary_max_chars=20)

    llm_client = LlmClient(压低上限的配置)
    builder = MemoryDraftBuilder.build(llm_client)

    batch = builder.build_drafts(原始文本)

    _print_section("用例二：摘要字符上限压到 20 + 话题分散的笔记", batch.render_text())
