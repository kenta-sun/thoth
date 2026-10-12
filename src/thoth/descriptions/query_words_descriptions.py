"""query_words 工具说明：精简查询协议并拼接统一标签目录，加载时不连接数据库。"""

from thoth.common.tags import TAG_OPTIONS_DESCRIPTION


QUERY_WORDS_DESCRIPTION = """查询未删除的日语单词，不修改数据。唯一参数 text 为 JSON 对象字符串，无 Markdown。
四个可选字段：where 筛选、fields 返回字段数组、sort 按优先级排列的 [[字段,"asc"或"desc"]]、limit 正整数。
省略 where 不额外筛选；省略 fields 返回全部业务字段；省略 sort 按单词 ID 升序；省略 limit 返回全部。
业务字段：word、common_form、hiragana、meaning、tags、usage_count、miss_count，不含状态和审计字段。
where 不同字段及同字段多个操作均为 AND：直接值表示相等，{"in":[值,...]} 表示任选其一。
四个文本字段支持相等/in；次数字段支持相等/in/gt/gte/lt/lte，值为 BIGINT 范围内非负整数。
tags 仅支持 in，匹配拥有任一指定编码的词，不推断标签层级；除 tags 外所有业务字段可排序。
仅 common_form 支持 {"like":"模式"}，使用 PostgreSQL LIKE："食%"开头、"%る"结尾、"%食%"包含，
_ 匹配单个字符。模式由调用方提供，不自动加通配符；反斜杠转义字面通配符，JSON 中反斜杠须写两次。
无统计记录按 0 筛选、排序和返回。排序并列按 ID 升序；筛选和排序字段不必放入 fields。
返回 {"results":[对象,...]}，只含选定字段；单字段也返回对象，无匹配为空数组，tags 为编码数组。
仅接受上述结构，不接受 null、重复键、未知字段/操作、空 fields/sort/in/字段条件或重复投影/排序字段。
空对象 {} 和空 where 合法；字符串原文匹配；limit 不超过 BIGINT 上限，不接受布尔值。
示例（展示解析后的对象，调用时序列化为 text 字符串）：
{"where":{"word":{"in":["食べる","学校"]}},"fields":["common_form"]}
{"where":{"common_form":{"like":"%食%"}},"sort":[["usage_count","asc"],["miss_count","desc"]],"limit":100}
""" + "\n" + TAG_OPTIONS_DESCRIPTION
