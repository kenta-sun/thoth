"""表实体层：定义 WordMissEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class WordMissEntity:
    """word_miss_tbl 的陌生词统计记录，按单词汇总默写错误和向 AI 询问的次数。"""

    user_id: int | None = None  # 关联 user_tbl.id，与 word_id 构成联合主键。
    word_id: int | None = None  # 关联 word_tbl.id 的联合主键字段，每个用户对每个单词最多一条陌生统计。
    miss_count: int | None = None  # 默写错误及向 AI 询问该词的累计次数；表默认 0，并限制非负。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。

