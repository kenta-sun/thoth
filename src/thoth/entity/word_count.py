"""表实体层：定义 WordCountEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class WordCountEntity:
    """word_count_tbl 的计数记录，按用户、单词和类型保存累计次数。"""

    user_id: int | None = None  # 关联 user_tbl.id，与 word_id、count_type 构成联合主键。
    word_id: int | None = None  # 关联 word_tbl.id 的联合主键字段，与 user_id、count_type 共同标识统计记录。
    count_type: str | None = None  # 关联 count_type_tbl.code 的联合主键字段，标识统计类型。
    count_value: int | None = None  # 对应类型的累计次数；数据库默认 0，并限制非负。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。

