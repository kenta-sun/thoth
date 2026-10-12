"""add_update_words 工具的对外说明，供统一入口注册时使用。"""

from thoth.common.tags import TAG_OPTIONS_DESCRIPTION

ADD_UPDATE_WORDS_DESCRIPTION = """批量新增或修改日语单词，以 word 为唯一判重和更新定位依据。

唯一参数 text 是 JSON 数组字符串，每个元素代表一个单词。以下展示解析后的结构，
中文值为字段说明；实际调用时应填写真实信息，并将整个数组序列化为字符串传入 text。
text 不得包含 Markdown 标记或额外说明。

[
  {
    "word": "字符串；单词基本形式，如食べる。始终必填且不能为空，用于判重和更新定位。",
    "common_form": "字符串；单词常用写法。新增时必填，可以与 word 相同；更新时仅需提供要修改的值。",
    "hiragana": "字符串；单词的平假名读音。新增时必填；更新时仅需提供要修改的值。",
    "meaning": "字符串；单词的中文释义。新增时必填；更新时仅需提供要修改的值。",
    "tags": ["必填的已有标签编码，如 v、v2，至少一个"],
    "operation": {
      "action": "字符串；仅允许 create 或 update。整个 operation 可以省略，省略时默认 create。create：不存在则新增，已存在则跳过。update：不存在则新增，已存在则修改。"
    }
  }
]

执行规则：
- 新增时 word、common_form、hiragana、meaning 都必须是非空字符串；缺失、null、
  空字符串或纯空白字符串均报错，不自动补填。update 遇到不存在的单词时也适用此要求。
- 修改已有单词时，只更新 common_form、hiragana、meaning 中传入了有效值的字段。
  未传入、null、空字符串或纯空白字符串均忽略，不报错、不清空原值；仅修改标签也执行更新。
- tags 在新增和更新时均必填，必须是非空字符串数组，不接受缺失、null 或空数组。
  编码为 1～32 位英文字母、数字或下划线，按原文匹配，不去空格或转换大小写。
  重复编码去重；所有编码必须存在于 tag_tbl，任一不存在则整项失败。
  AI 找不到合适的已有标签时，不要提交该单词，不得随意选标签凑数或编造标签。
- update 必须提供完整的新标签列表：删除该单词所有旧关联，再插入全部新关联。
  即使列表相同也重建，不支持清空标签。create 遇到已有词仍校验标签，合法后整项跳过。
- 单词信息与标签关联共用单项事务，删除或插入标签失败时全部回滚，其他单词继续处理。
- 省略整个 operation 时默认 create；传入 operation 时必须且只能包含合法的 action。
  operation 仅控制本次操作，不存入单词表。
- 按 word 原文精确匹配，包括已标记删除的记录。本工具不修改 word，也不改变记录状态。
- text 必须是非空数组。只接受上述字段及嵌套结构。同批重复 word 的所有项均失败，
  其他词继续处理。字段类型错误或未知字段均报错。JSON 不得包含重复键。
- 每项独立处理，单项失败不影响其他项；返回 results 数组，按输入顺序包含
  index（从 0 开始）、word、status：created（已新增）、updated（已修改）、
  skipped（已跳过）或 failed（失败）。跳过和失败时附 reason；缺少新增信息时附 fields。
- text 格式错误、无法连接数据库或查询已有单词失败时返回工具错误。
""" + "\n" + TAG_OPTIONS_DESCRIPTION
