"""表实体层：定义 WordStatusEntity，供业务层和数据访问层传递表记录。

字段允许为 None 且默认 None；实体不执行类型、非空或业务校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class WordStatusEntity:
    """word_sts_tbl 的状态字典记录，供单词表通过状态编码关联。"""

    code: str | None = None  # 人工指定的状态主键，表约束为单个大写字母；A=正在使用，D=被删除。
    description: str | None = None  # 状态的中文说明。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。

