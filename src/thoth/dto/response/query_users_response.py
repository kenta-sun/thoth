"""用户查询响应：仅暴露已有用户名，不暴露数据库主键。"""

from pydantic import Field
from thoth.dto.response.common import ResponseModel


class QueryUserResult(ResponseModel):
    """承载一个可用于工具调用的已有用户名。"""

    username: str = Field(description="已有用户名，保留原文和大小写。")


class QueryUsersResponse(ResponseModel):
    """按数据库用户 ID 升序返回用户名。"""

    results: list[QueryUserResult] = Field(description="已有用户名列表；无用户时为空数组。")
