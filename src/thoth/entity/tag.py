"""表实体层：定义 TagEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class TagEntity:
    """tag_tbl 的标签字典记录，保存标签编码及其中日文名称。"""

    code: str | None = None  # 人工指定的标签主键；表约束仅接受英文字母、数字和下划线。
    zh_name: str | None = None  # 标签的中文名称。
    jp_name: str | None = None  # 标签的日文名称。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。

