"""表实体层：定义 WordTagEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class WordTagEntity:
    """word_tag_tbl 的单词标签关联记录，一条记录表示一个单词具有一个标签。"""

    word_id: int | None = None  # 关联 word_tbl.id，与 tag_code 组成联合主键。
    tag_code: str | None = None  # 关联 tag_tbl.code，与 word_id 组成联合主键。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。

