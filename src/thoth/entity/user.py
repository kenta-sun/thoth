"""实体层：承载用户表记录，由用户查询和统计归属校验使用。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class UserEntity:
    """用户表记录；字段均允许为空，不在实体内执行业务校验。"""

    id: int | None = None  # 数据库生成的用户主键，供统计表关联。
    username: str | None = None  # 用户手动维护的唯一用户名，按原文区分大小写。
    created_at: datetime | None = None  # 数据库生成的创建时间。
    updated_at: datetime | None = None  # 最后更新时间，由写入方维护。
    created_by: str | None = None  # 创建者标识，默认数据库角色。
    updated_by: str | None = None  # 最后修改者标识，默认数据库角色。
