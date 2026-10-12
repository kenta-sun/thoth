"""count_word_miss 的独立 MCP 说明，由工具入口注册。"""

COUNT_WORD_MISS_DESCRIPTION = """按单词原文批量将错误次数 miss_count 加一。
唯一参数 text 为 JSON 字符串数组的字符串，解析后示例：["食べる","飲む"]。
不接受逗号分隔格式，不需要 word 对象、ID、fields、表名或增量。
空数组正常返回空 results；null、空字符串、纯空白、非字符串及非法数据库文本
逐项 skipped 并附原因，无法安全输出 word 时为 null。有效词保留原文，不去首尾空格。
同批重复词只对首次出现项计数，后续项 skipped，reason 指明首次 index。
不存在或状态为 D 的词 skipped，统一说明单词不存在。
批量查询主表后，批量插入缺失统计行（初始值 0，已有行不变），再一次批量加一。
仅操作 word_miss_tbl，不修改另一张统计表。没有有效词时不读取配置、不连接数据库。
不设置跨语句事务；初始化成功而加一失败时，零值记录保留。
批量写入失败时待计数项均 failed，过滤项仍 skipped，不自动逐项重试。
写入时重新检查主表状态，以实际更新记录返回成功；处理中消失的记录 skipped。
返回 results，按原输入顺序含 index（零基）、word、status；updated 项包含
counts: {"miss_count": 本次更新后的值}，skipped 和 failed 项包含 reason。
非法 JSON、非数组顶层、重复对象键、非标准数值，以及配置、连接、初始查询失败
返回工具错误。计数不提供请求去重或自动重试，响应丢失时不要盲目重试。
"""
