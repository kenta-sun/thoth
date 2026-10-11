"""JSON 通用辅助函数：供解析器拒绝重复对象键及非标准数值常量。

作为 json.loads 的钩子使用，不负责具体业务字段校验。
"""

from __future__ import annotations

from typing import Any


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """将 JSON 对象的键值对还原为字典；重复键抛出 ValueError，避免静默覆盖。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 对象包含重复字段：{key!r}。")
        result[key] = value
    return result


def reject_json_constant(value: str) -> None:
    """拒绝解析器默认容许的 NaN、Infinity 等非标准 JSON 数值，抛出 ValueError。"""
    raise ValueError(f"JSON 不允许使用 {value}。")
