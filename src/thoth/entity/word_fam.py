"""表实体层：定义 WordFamEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class WordFamEntity:
    """word_fam_tbl 的用户单词熟悉度记录，保存指定用户对一个单词的当前熟悉度。"""

    user_id: int | None = None  # 关联 user_tbl.id，与 word_id 组成联合主键。
    word_id: int | None = None  # 关联 word_tbl.id，与 user_id 组成联合主键。
    tag_code: str | None = None  # 关联 tag_tbl.code，表示该用户对该词的当前熟悉度标签。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。

