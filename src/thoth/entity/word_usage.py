"""表实体层：定义 WordUsageEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class WordUsageEntity:
    """word_usage_tbl 的使用统计记录，按单词汇总出题或写文章时的累计使用次数。"""

    user_id: int | None = None  # 关联 user_tbl.id，与 word_id 构成联合主键。
    word_id: int | None = None  # 关联 word_tbl.id 的联合主键字段，每个用户对每个单词最多一条使用统计。
    usage_count: int | None = None  # 出题或写文章时使用该词的累计次数；表默认 0，并限制非负。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。

