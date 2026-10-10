"""仅通过 save_words 暴露受限制的单词保存接口。"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from thoth.config import get_settings
from thoth.db.connection import DatabaseError, open_connection
from thoth.db.word_repo import WordRepository
from thoth.word_service import parse_words_text, save_word_batch

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

mcp = FastMCP(name="thoth-words", strict_input_validation=True)


@mcp.tool(description=SAVE_WORDS_DESCRIPTION)
def save_words(text: str) -> dict[str, list[dict[str, Any]]]:
    """解析输入后调用业务层，向 MCP 返回结构化的逐项结果。"""
    try:
        items = parse_words_text(text)
        settings = get_settings()
        with open_connection(settings) as connection:
            repository = WordRepository(connection, operator=settings.operator)
            return save_word_batch(items, repository)
    except (ValueError, DatabaseError) as exc:
        raise ToolError(str(exc)) from exc


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False, log_level="ERROR")
