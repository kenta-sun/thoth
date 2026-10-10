"""读取单词服务的运行配置，供 MCP 入口和数据库连接层使用。

首次调用 get_settings 时才读取本地配置和环境变量，并缓存解析后的 Settings。
模块导入本身不加载配置、不连接数据库，便于 MCP 工具发现和单元测试。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 配置文件位置以项目目录为准，避免 MCP 客户端的启动目录影响配置读取。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    """已解析的运行配置；冻结字段以防共享的缓存配置被调用方修改。"""

    pg_dsn: str = field(repr=False)  # PostgreSQL 连接字符串；可能含凭证，不纳入 repr。
    operator: str = "THOTH_MCP"  # 写入 created_by、updated_by 的操作者标识。


def _load_env_file() -> None:
    """保留本地配置文件支持，已设置的进程环境变量优先。"""
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)


def load_settings() -> Settings:
    """读取并校验一次配置，不使用 get_settings 的缓存。

    已设置的进程环境变量优先于本地配置文件；连接字符串两端空白会被去掉。
    操作者未提供或仅有空白时使用 THOTH_MCP。

    Returns:
        可交给连接层和仓储层使用的配置对象。

    Raises:
        ValueError: 缺少有效连接字符串，或操作者超过审计列允许的 128 个字符。
    """
    _load_env_file()
    pg_dsn = os.getenv("THOTH_PG_DSN", "").strip()
    if not pg_dsn:
        raise ValueError("未配置 THOTH_PG_DSN，请提供 PostgreSQL 连接字符串。")

    operator = os.getenv("THOTH_OPERATOR", "").strip() or "THOTH_MCP"
    # 在业务入口报告可读的配置错误，避免每条写入都触发 VARCHAR(128) 超长错误。
    if len(operator) > 128:
        raise ValueError("THOTH_OPERATOR 不能超过 128 个字符。")
    return Settings(pg_dsn=pg_dsn, operator=operator)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """首次调用时加载配置，后续复用同一对象；配置错误由调用方处理。

    运行中修改环境变量不会自动刷新缓存；重启进程后重新加载。
    测试需要切换配置时，可调用 get_settings.cache_clear() 清理缓存。
    """
    return load_settings()
