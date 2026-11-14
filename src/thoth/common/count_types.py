"""公共计数类型定义：集中提供字典编码、说明与校验，工具注册时不访问数据库。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CountTypeDefinition:
    """承载支持的计数类型及其业务含义，不代表数据库中的已存在记录。"""

    code: str  # 计数类型编码，对应 count_type_tbl 主键。
    description: str  # 字典中的中文业务说明。
    name: str  # 面向工具调用者的计数名称。


COUNT_TYPE_DEFINITIONS = (
    CountTypeDefinition("usage", "见到单词的次数", "使用次数"),
    CountTypeDefinition("miss", "没记起单词的次数", "陌生次数"),
    CountTypeDefinition("inf_miss", "不认识活用形式、不会变形或变形答错的次数，归到对应词典形", "活用不熟悉次数"),
)
COUNT_TYPE_CODES = tuple(item.code for item in COUNT_TYPE_DEFINITIONS)
COUNT_TYPE_OPTIONS_DESCRIPTION = "计数类型：" + "；".join(
    f"{item.code}={item.name}（{item.description}）" for item in COUNT_TYPE_DEFINITIONS
) + "。一次仅增加所选类型，不联动其他计数。"


def validate_count_type(value: str) -> str:
    """返回合法编码；非字符串或不支持的编码抛出 ValueError，不归一化输入。"""
    if not isinstance(value, str) or value not in COUNT_TYPE_CODES:
        raise ValueError("count_type 必须是支持的字符串编码。" + COUNT_TYPE_OPTIONS_DESCRIPTION)
    return value
