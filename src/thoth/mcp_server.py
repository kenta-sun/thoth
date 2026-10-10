"""MCP 协议入口：将 save_words 工具调用交给单词业务层。

一次调用依次完成 JSON 解析、配置加载、打开连接、逐项保存和结果序列化。
本层负责把整批失败转换为 MCP 工具错误；单项失败由业务层保留在 results 中。
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from thoth.config import get_settings
from thoth.db.connection import DatabaseError, open_connection
from thoth.db.word_repo import WordRepository
from thoth.word_service import parse_words_text, save_word_batch, serialize_word_batch

# 这是 MCP 客户端和调用工具的 AI 能看到的接口说明；调整协议时需与业务实现同步。
SAVE_WORDS_DESCRIPTION = """批量新增或修改日语单词，以 word 为唯一判重和更新定位依据。

唯一参数 text 是 JSON 数组字符串，每个元素代表一个单词。以下展示解析后的结构，
中文值为字段说明；实际调用时应填写真实信息，并将整个数组序列化为字符串传入 text。
text 不得包含 Markdown 标记或额外说明。

[
  {
    "word": "字符串；单词基本形式，如食べる。始终必填且不能为空，用于判重和更新定位。",
    "common_form": "字符串；单词常用写法。新增时必填，可以与 word 相同；更新时仅需提供要修改的值。",
    "hiragana": "字符串；单词的平假名读音。新增时必填；更新时仅需提供要修改的值。",
    "meaning": "字符串；单词的中文释义。新增时必填；更新时仅需提供要修改的值。",
    "operation": {
      "action": "字符串；仅允许 create 或 update。整个 operation 可以省略，省略时默认 create。create：不存在则新增，已存在则跳过。update：不存在则新增，已存在则修改。"
    }
  }
]

执行规则：
- 新增时 word、common_form、hiragana、meaning 都必须是非空字符串；缺失、null、
  空字符串或纯空白字符串均报错，不自动补填。update 遇到不存在的单词时也适用此要求。
- 修改已有单词时，只更新 common_form、hiragana、meaning 中传入了有效值的字段。
  未传入、null、空字符串或纯空白字符串均忽略，不报错、不清空原值；无有效修改字段则跳过。
- 省略整个 operation 时默认 create；传入 operation 时必须且只能包含合法的 action。
  operation 仅控制本次操作，不存入单词表。
- 按 word 原文精确匹配，包括已标记删除的记录。本工具不修改 word，也不改变记录状态。
- text 必须是非空数组。只接受上述字段及嵌套结构。同批重复 word 的所有项均失败，
  其他词继续处理。字段类型错误或未知字段均报错。JSON 不得包含重复键。
- 每项独立处理，单项失败不影响其他项；返回 results 数组，按输入顺序包含
  index（从 0 开始）、word、status：created（已新增）、updated（已修改）、
  skipped（已跳过）或 failed（失败）。跳过和失败时附 reason；缺少新增信息时附 fields。
- text 格式错误、无法连接数据库或查询已有单词失败时返回工具错误。
"""

# 在协议层拒绝类型不符的入参，例如直接把数组传给要求字符串的 text。
mcp = FastMCP(name="thoth-words", strict_input_validation=True)


@mcp.tool(description=SAVE_WORDS_DESCRIPTION)
def save_words(text: str) -> dict[str, list[dict[str, Any]]]:
    """处理一次批量保存调用，并管理本次调用所用的数据库连接。

    Args:
        text: 非空 JSON 数组字符串；具体字段与操作规则见工具说明。

    Returns:
        可由 MCP 输出为 JSON 的 results 数组，按输入顺序列出各项处理结果。
        单项校验或保存失败仍返回正常工具响应，该项的 status 为 failed。

    Raises:
        ToolError: 整批 JSON 格式错误、配置错误、连接失败或批量查询失败。
    """
    try:
        # 先解析再建立连接，整批格式错误时无需读取配置或访问数据库。
        items = parse_words_text(text)
        settings = get_settings()
        # 同批复用一条连接；每项保存的事务由仓储管理，连接在退出 with 时关闭。
        with open_connection(settings) as connection:
            repository = WordRepository(connection, operator=settings.operator)
            # 业务层传递结果对象，直到协议输出处才转换成规定形状的字典。
            return serialize_word_batch(save_word_batch(items, repository))
    except (ValueError, DatabaseError) as exc:
        # 这里只处理会使整批无法继续的错误；数据库错误文本已经由连接/仓储层脱敏。
        raise ToolError(str(exc)) from exc


if __name__ == "__main__":
    # stdio 的标准输出用于协议通信，关闭启动横幅以免混入工具消息。
    mcp.run(transport="stdio", show_banner=False, log_level="ERROR")
