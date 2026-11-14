"""表实体层：定义 CountTypeEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class CountTypeEntity:
    """count_type_tbl 的计数类型字典记录，供统计表通过计数类型编码关联。"""

    code: str | None = None  # 人工指定的计数类型主键，miss=陌生次数，usage=使用次数。
    description: str | None = None  # 计数类型的中文说明。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。

