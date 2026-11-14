"""计数请求定义：从公共字典生成 Schema 枚举，并在进入业务层前校验编码。"""

from typing import Annotated
from pydantic import AfterValidator, Field
from thoth.common.count_types import (
    COUNT_TYPE_CODES, COUNT_TYPE_OPTIONS_DESCRIPTION, validate_count_type,
)


CountType = Annotated[
    str,
    Field(strict=True, description=COUNT_TYPE_OPTIONS_DESCRIPTION,
          json_schema_extra={"enum": list(COUNT_TYPE_CODES)}),
    AfterValidator(validate_count_type),
]
