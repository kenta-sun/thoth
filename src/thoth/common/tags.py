"""公共标签目录：唯一人工维护来源，供工具说明和显式初始化 SQL 生成命令使用。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TagDefinition:
    """承载一个预置标签的编码和显示名称，不代表数据库中的已存在记录。"""

    code: str  # 标签编码，对应 tag_tbl 的主键。
    zh_name: str  # 面向中文使用者的标签名称。
    jp_name: str  # 日文标签名称，供初始化数据库使用。


TAG_DEFINITIONS = (
    TagDefinition("v", "动词", "動詞"),
    TagDefinition("v1", "Ⅰ类动词", "Ⅰ類動詞"),
    TagDefinition("v2", "Ⅱ类动词", "Ⅱ類動詞"),
    TagDefinition("v3", "Ⅲ类动词", "Ⅲ類動詞"),
    TagDefinition("adj", "形容词", "形容詞"),
    TagDefinition("adj_i", "イ形容词", "イ形容詞"),
    TagDefinition("adj_na", "ナ形容词", "ナ形容詞"),
    TagDefinition("n", "名词", "名詞"),
    TagDefinition("adv", "副词", "副詞"),
    TagDefinition("num", "数量词", "数量詞"),
)

# description 在模块加载时直接引用生成结果，不查询数据库。
TAG_OPTIONS_DESCRIPTION = "可用标签编码：" + "；".join(
    f"{tag.code}={tag.zh_name}" for tag in TAG_DEFINITIONS
) + "。"
