"""公共配置层：读取指定配置文件和进程变量，供业务服务建立数据库连接。

Docker 服务固定读取镜像内的 .env.prd；集成测试显式指定 .env.test。
不自动加载公共 .env，不按环境名称切换文件，也不修改进程变量。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

# 源码在容器内固定为 /app/src/thoth，配置随镜像复制到 /app/.env.prd。
PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class Settings:
    """承载数据库连接配置，展示对象时隐藏连接凭证。"""

    pg_dsn: str = field(repr=False)  # PostgreSQL 连接串，包含实际库名及连接凭证。


def load_settings(*, config_file: Path | None = None) -> Settings:
    """合并单个配置文件和进程变量，进程值优先。

    Args:
        config_file: 明确指定的配置文件，必须存在；None 时只读取进程变量。
            不展开文件内的 ${VAR}，避免改变密码中的字面字符。

    Returns:
        校验后的数据库连接配置，不检查或限制数据库名称。

    Raises:
        ValueError: 指定文件不存在、连接串缺失或为空。
    """
    values = {}
    if config_file is not None:
        if not config_file.is_file():
            raise ValueError(f"缺少配置文件 {config_file.name}。")
        values = dotenv_values(config_file, interpolate=False)
    # 显式空进程值也覆盖文件值，避免配置错误时静默回退。
    values = {**values, **os.environ}
    pg_dsn = (values.get("THOTH_PG_DSN") or "").strip()
    if not pg_dsn:
        raise ValueError("未配置 THOTH_PG_DSN，请在配置文件或进程变量中提供连接字符串。")
    return Settings(pg_dsn=pg_dsn)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """缓存镜像内 .env.prd 配置；修改文件后需重新构建并重建容器。"""
    return load_settings(config_file=PROJECT_ROOT / ".env.prd")
