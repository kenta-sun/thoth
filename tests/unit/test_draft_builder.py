"""
记忆提取的单元测试。

测试范围：**只测到落表之前**。

也就是只覆盖 ``MemoryDraftBuilder``，即「原始文本 → 记忆草稿」这一整个阶段：
粗提取 → 分类 → 按类型精炼 → 生成摘要。
查重与写库属于 ``ExtractionPipeline`` 的另一个阶段，不在本文件范围内。

因此这两个用例：
- 不联网（大模型被 ``FakeLlmClient`` 替换）；
- 不连数据库（``MemoryDraftBuilder`` 根本不持有数据库对象）。

两个用例分别覆盖：
1. ``test_混合文本只保留个人信息与事件``：主路径。验证分类分流、精炼提示词选择、丢弃行为。
2. ``test_摘要超长会被压回上限且散乱记忆被挂起``：两条边界。验证摘要长度兜底与散乱挂起。

每个用例都会把最终产出的记忆数据打印到控制台，便于人工过目。
pyproject 里已经配了 ``-s``，直接 ``pytest`` 就能看到输出。
"""

from __future__ import annotations

from thoth.extraction.draft_builder import MemoryDraftBuilder
from thoth.extraction.extractor import MemoryExtractor
from thoth.extraction.summarizer import MemorySummarizer
from thoth.models import ClassificationLabel, MemoryType, SummaryResult
from tests.support.fake_llm import FakeLlmClient, build_test_settings


def _build_builder(fake_llm: FakeLlmClient) -> MemoryDraftBuilder:
    """
    用假客户端组装草稿构建器。

    入参：
    - fake_llm : 脚本化的假大模型客户端。
    返回：
    - MemoryDraftBuilder 实例。

    这里手动装配而不用 ``MemoryDraftBuilder.build()``，是为了明确表达
    构建器只依赖 extractor 与 summarizer 这两个协作对象，与数据库无关。
    """
    return MemoryDraftBuilder(
        extractor=MemoryExtractor(fake_llm),
        summarizer=MemorySummarizer(fake_llm),
    )


def _print_section(title: str, body: str) -> None:
    """把一段内容以带标题的形式打到控制台。"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)
    print(body)
    print("=" * 70)


# ============================================================
# 用例一：主路径
# ============================================================


def test_混合文本只保留个人信息与事件():
    """
    一段混合了个人信息、事件与技术知识的文本，应当只产出前两类记忆。

    验证点：
    1. 技术知识被分类阶段判为 DROP，不出现在产出里，也不产生任何提示；
    2. 个人信息走了个人档案精炼提示词，事件走了事件精炼提示词；
    3. 每条草稿的类型、摘要、正文、原始片段都正确落位；
    4. 全程没有触发向量化（``FakeLlmClient.embed`` 会直接断言失败），
       证明「产出记忆数据」这一阶段确实与落表解耦了。
    """
    原始文本 = (
        "我目前住在大阪，主要做 Java 后端开发。"
        "上周五我去面试了一家医疗系统公司。"
        "顺便说一句，pgvector 支持余弦距离和 L2 距离。"
    )

    个人信息粗记忆 = "我目前住在大阪，主要做 Java 后端开发。"
    事件粗记忆 = "上周五我去面试了一家医疗系统公司。"
    技术知识粗记忆 = "pgvector 支持余弦距离和 L2 距离。"

    个人信息正文 = "用户目前居住在大阪，主要从事 Java 后端开发工作。"
    事件正文 = "上周五，用户前往一家医疗系统公司参加了面试。"

    fake_llm = FakeLlmClient(
        settings=build_test_settings(),
        coarse_memories=[
            个人信息粗记忆,
            事件粗记忆,
            技术知识粗记忆,
            # 混一条纯空白进去，验证清洗逻辑：它不该走到分类环节。
            "   ",
        ],
        classifications={
            个人信息粗记忆: ClassificationLabel.PERSONAL,
            事件粗记忆: ClassificationLabel.EVENT,
            技术知识粗记忆: ClassificationLabel.DROP,
        },
        refinements={
            个人信息粗记忆: 个人信息正文,
            事件粗记忆: 事件正文,
        },
        summaries={
            个人信息正文: [
                SummaryResult(
                    summary="用户居住在大阪，从事 Java 后端开发。",
                    needs_resplit=False,
                    resplit_reason="",
                )
            ],
            事件正文: [
                SummaryResult(
                    summary="用户上周五面试了一家医疗系统公司。",
                    needs_resplit=False,
                    resplit_reason="",
                )
            ],
        },
    )

    batch = _build_builder(fake_llm).build_drafts(原始文本)

    _print_section("用例一：混合文本，只保留个人信息与事件", batch.render_text())

    # 空白项被清洗掉，只有 3 条真正进入分类
    assert fake_llm.classified == [个人信息粗记忆, 事件粗记忆, 技术知识粗记忆]

    # 技术知识被丢弃，没有进入精炼环节
    assert [call.coarse_memory for call in fake_llm.refine_calls] == [
        个人信息粗记忆,
        事件粗记忆,
    ]

    # 按类型选对了精炼提示词
    assert [call.detected_type for call in fake_llm.refine_calls] == [
        MemoryType.PERSONAL,
        MemoryType.EVENT,
    ]

    # 最终产出两条草稿，没有待重拆的
    assert len(batch.drafts) == 2
    assert batch.pending_resplit == []

    个人草稿, 事件草稿 = batch.drafts

    assert 个人草稿.memory_type is MemoryType.PERSONAL
    assert 个人草稿.raw_content == 个人信息粗记忆
    assert 个人草稿.refined_content == 个人信息正文
    assert 个人草稿.summary == "用户居住在大阪，从事 Java 后端开发。"

    assert 事件草稿.memory_type is MemoryType.EVENT
    assert 事件草稿.raw_content == 事件粗记忆
    assert 事件草稿.refined_content == 事件正文
    assert 事件草稿.summary == "用户上周五面试了一家医疗系统公司。"

    # 摘要各调用一次，粗提取只调一次
    assert fake_llm.extract_call_count == 1
    assert fake_llm.summarize_call_count == 2


# ============================================================
# 用例二：两条边界
# ============================================================


def test_摘要超长会被压回上限且散乱记忆被挂起():
    """
    两条边界情况：

    1. **摘要超长**：首次生成的摘要超过字符上限时，摘要器会带着失败反馈重试一次；
       重试后的合规摘要应当被采用，最终草稿里的摘要长度不超过上限。
    2. **记忆散乱**：模型判定 ``needs_resplit=True`` 的记忆不进入草稿，
       而是挂到 ``pending_resplit`` 里等待重新拆分，因此不会被写库。

    这里刻意把上限压到 20 个字符，方便构造超长场景。
    """
    上限 = 20

    超长粗记忆 = "上周五我去大阪面试了一家做医疗系统的公司，聊得还不错。"
    散乱粗记忆 = "我住在大阪，也在学日语，还在研究 Neo4j。"

    超长正文 = "上周五，用户前往大阪面试了一家医疗系统公司，面试过程顺利。"
    散乱正文 = "用户居住在大阪，同时在学习日语并研究 Neo4j。"

    首次超长摘要 = "用户上周五前往大阪面试了一家医疗系统公司且过程顺利"
    重试合规摘要 = "用户上周五赴大阪面试"

    # 前置确认测试数据本身符合预期，否则断言会失去意义
    assert len(首次超长摘要) > 上限
    assert len(重试合规摘要) <= 上限

    fake_llm = FakeLlmClient(
        settings=build_test_settings(summary_max_chars=上限),
        coarse_memories=[超长粗记忆, 散乱粗记忆],
        classifications={
            超长粗记忆: ClassificationLabel.EVENT,
            散乱粗记忆: ClassificationLabel.PERSONAL,
        },
        refinements={
            超长粗记忆: 超长正文,
            散乱粗记忆: 散乱正文,
        },
        summaries={
            # 队列有两个元素：第一次返回超长的，重试时返回合规的
            超长正文: [
                SummaryResult(summary=首次超长摘要, needs_resplit=False, resplit_reason=""),
                SummaryResult(summary=重试合规摘要, needs_resplit=False, resplit_reason=""),
            ],
            散乱正文: [
                SummaryResult(
                    summary="用户的居住地与学习情况",
                    needs_resplit=True,
                    resplit_reason="混合了居住地、语言学习、技术研究三个互不相关的主题",
                )
            ],
        },
    )

    batch = _build_builder(fake_llm).build_drafts("随便一段原始文本")

    _print_section("用例二：摘要超长压回上限 + 散乱记忆挂起", batch.render_text())

    # 只有超长那条进了草稿，散乱那条被挂起
    assert len(batch.drafts) == 1
    assert len(batch.pending_resplit) == 1

    草稿 = batch.drafts[0]
    assert 草稿.memory_type is MemoryType.EVENT
    assert 草稿.summary == 重试合规摘要
    assert len(草稿.summary) <= 上限

    挂起项 = batch.pending_resplit[0]
    assert 挂起项.memory_type is MemoryType.PERSONAL
    assert 挂起项.refined_content == 散乱正文
    assert "互不相关" in 挂起项.reason

    # 摘要共调用 3 次：超长那条 2 次（首次 + 重试），散乱那条 1 次
    assert fake_llm.summarize_call_count == 3
