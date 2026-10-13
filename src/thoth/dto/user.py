"""用户业务结果：仅向上层传递已有用户名，不暴露数据库生成主键。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserNameResult:
    """承载一个已有用户的业务名称。"""

    username: str  # 用户原名，保留大小写，用于业务调用的精确匹配。
