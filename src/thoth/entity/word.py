"""表实体层：定义 WordEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class WordEntity:
    """word_tbl 的单词记录，承载输入信息及数据库返回的标识、状态和审计字段。"""

    id: int | None = None  # 单词主键；未显式指定时由数据库 identity 生成。
    word: str | None = None  # 单词基本形式；表内唯一，按原文判重和定位，包含已删除记录。
    common_form: str | None = None  # 单词常用写法。
    hiragana: str | None = None  # 单词的平假名读音。
    meaning: str | None = None  # 单词的中文释义。
    status_code: str | None = None  # 关联 word_sts_tbl.code；A=正在使用，D=被删除，表默认 A。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新由 SQL 维护。
    created_by: str | None = None  # 创建者标识；由数据库 CURRENT_USER 记录。
    updated_by: str | None = None  # 最后修改者标识；实际更新时由数据库 CURRENT_USER 记录。

