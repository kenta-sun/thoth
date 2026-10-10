"""单词服务的数据库配置；首次调用工具时才加载。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    pg_dsn: str = field(repr=False)
    operator: str = "THOTH_MCP"


def _load_env_file() -> None:
    """保留本地配置文件支持，已设置的进程环境变量优先。"""
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)


def load_settings() -> Settings:
    _load_env_file()
    pg_dsn = os.getenv("THOTH_PG_DSN", "").strip()
    if not pg_dsn:
        raise ValueError("未配置 THOTH_PG_DSN，请提供 PostgreSQL 连接字符串。")

    operator = os.getenv("THOTH_OPERATOR", "").strip() or "THOTH_MCP"
    if len(operator) > 128:
        raise ValueError("THOTH_OPERATOR 不能超过 128 个字符。")
    return Settings(pg_dsn=pg_dsn, operator=operator)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
