"""请求公共定义：提供固定对象配置和多个工具共用的用户名参数。"""

from typing import Annotated
from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _validate_username(value: str) -> str:
    """拒绝首尾空白和数据库不可接受的文本，保留用户名原文与大小写。"""
    if value != value.strip() or "\x00" in value:
        raise ValueError("username 不能包含首尾空白或空字符。")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("username 必须能编码为 UTF-8。") from None
    return value


Username = Annotated[
    str,
    Field(min_length=1, max_length=128, description="已有用户名，区分大小写，无首尾空白；不存在时拒绝调用，不自动创建用户。"),
    AfterValidator(_validate_username),
]


class RequestModel(BaseModel):
    """禁止未知字段和隐式类型转换的对外请求对象。"""

    model_config = ConfigDict(extra="forbid", strict=True)
