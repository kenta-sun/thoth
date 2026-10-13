"""响应公共模型：禁止未知字段并提供按出现情况或空值省略的序列化规则。"""

from typing import ClassVar
from pydantic import BaseModel, ConfigDict, model_serializer


class ResponseModel(BaseModel):
    """对外结果基类，不接受未声明字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class OmitNoneResponse(ResponseModel):
    """省略无值的可选结果字段，同时保留指定字段的显式 null。"""

    preserve_null: ClassVar[frozenset[str]] = frozenset()

    @model_serializer(mode="wrap")
    def serialize_present(self, handler):
        """只省略可选空值，保留零计数和需要定位错误项的 word:null。"""
        return {name: value for name, value in handler(self).items()
                if value is not None or name in self.preserve_null}
