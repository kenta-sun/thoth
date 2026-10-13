"""公共配置层：按运行环境合并配置，供业务服务和数据库连接层使用。

配置目录可由进程 THOTH_CONFIG_DIR 指定；配置来自公共 .env、选定环境文件及进程变量，
不修改 os.environ。
业务服务首次读取时缓存配置；集成测试显式选择 test，不跟随日常环境。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from dotenv import dotenv_values

# 源码开发默认目录；安装包通过 THOTH_CONFIG_DIR 使用独立配置目录。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_DATABASES = MappingProxyType({"dev": "thoth_dev", "test": "thoth_test", "prd": "thoth_memory"})


@dataclass(frozen=True, slots=True)
class Settings:
    """承载选定环境的连接与审计配置，不在展示结果中暴露连接凭证。"""

    pg_dsn: str = field(repr=False)  # 当前环境的 PostgreSQL 连接串，可能含密码。
    operator: str = "THOTH_MCP"  # 写入 created_by、updated_by 的操作者标识。
    environment: str = "dev"  # 运行环境，仅允许 dev、test、prd。

    @property
    def expected_database(self) -> str:
        """返回当前环境必须连接的数据库名；非法环境在连接前报错。"""
        if self.environment not in ENV_DATABASES:
            raise ValueError("THOTH_ENV 必须为 dev、test 或 prd。")
        return ENV_DATABASES[self.environment]


def load_settings(environment: str | None = None, *, root: Path | None = None) -> Settings:
    """选择单个环境文件并合并配置，缺失配置时拒绝回退。

    Args:
        environment: 显式选择的环境；None 时按进程 THOTH_ENV、公共 .env 的顺序选择。
            测试入口固定传 test，覆盖日常环境选择。
        root: 显式配置目录，优先于进程变量；None 时使用 THOTH_CONFIG_DIR，
            未设置该变量时使用源码项目根目录。

    Returns:
        不含全局环境变量副作用的配置；值优先级为进程、环境文件、公共文件。

    Raises:
        ValueError: 配置目录变量为空、不是绝对路径或不是现有目录，或环境非法、
            环境文件缺失、连接串缺失、审计标识过长。
    """
    directory = root
    if directory is None:
        configured_directory = os.environ.get("THOTH_CONFIG_DIR")
        if configured_directory is None:
            directory = PROJECT_ROOT
        else:
            # 显式配置必须有效，不回退开发目录；绝对路径避免随客户端工作目录变化。
            directory = Path(configured_directory)
            if not configured_directory.strip() or not directory.is_absolute() or not directory.is_dir():
                raise ValueError("THOTH_CONFIG_DIR 必须为现有目录的绝对路径。")
    # 不插值，避免 dotenv 隐式读取进程变量或把其他环境的连接串带入。
    common = dotenv_values(directory / ".env", interpolate=False)
    selected = environment if environment is not None else os.environ.get("THOTH_ENV", common.get("THOTH_ENV"))
    selected = (selected or "").strip()
    if selected not in ENV_DATABASES:
        raise ValueError("THOTH_ENV 必须为 dev、test 或 prd，且不得为空。")
    env_file = directory / f".env.{selected}"
    if not env_file.is_file():
        raise ValueError(f"缺少环境配置文件 .env.{selected}。")
    if "THOTH_PG_DSN" in common:
        raise ValueError("公共 .env 不允许配置 THOTH_PG_DSN，请移入对应环境文件。")
    values = {**common, **dotenv_values(env_file, interpolate=False), **os.environ}
    pg_dsn = (values.get("THOTH_PG_DSN") or "").strip()
    if not pg_dsn:
        raise ValueError("未配置 THOTH_PG_DSN，请在环境文件或进程变量中提供连接字符串。")
    operator = (values.get("THOTH_OPERATOR") or "").strip() or "THOTH_MCP"
    if len(operator) > 128:
        raise ValueError("THOTH_OPERATOR 不能超过 128 个字符。")
    return Settings(pg_dsn=pg_dsn, operator=operator, environment=selected)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """缓存当前进程的业务配置；修改环境或文件后需重启，测试可清空缓存。"""
    return load_settings()
