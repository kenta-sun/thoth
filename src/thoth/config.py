"""
统一配置模块。

职责：
1. 从项目根目录的 ``.env`` 文件加载环境变量（不覆盖已存在的真实环境变量）。
2. 把所有运行期可调参数集中成一个不可变的 ``Settings`` 对象。
3. 提供 ``get_settings()`` 单例入口，避免各模块重复读取环境变量。

设计取舍：
- 所有配置项都给了默认值（除 ``OPENAI_API_KEY``），这样本地开发只要有 API Key 就能跑起来。
- 不使用 pydantic-settings，而是手写解析。原因是配置项很少，
  手写可以把「类型转换失败时给出中文报错」这件事控制得更精确。
- ``Settings`` 用 ``frozen=True``，防止业务代码在运行期偷偷改配置导致行为难以复现。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：本文件位于 <root>/src/thoth/config.py，因此向上三级即为项目根。
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# .env 文件路径。该文件已被 .gitignore 忽略，用于存放 API Key、数据库密码等敏感信息。
ENV_FILE_PATH = PROJECT_ROOT / ".env"


def _load_env_file() -> None:
    """
    加载 .env 文件。

    行为说明：
    - ``override=False``：已经存在于真实环境变量中的值优先，方便在 CI / 容器中覆盖。
    - 文件不存在时静默跳过，此时全部依赖真实环境变量。
    """
    if ENV_FILE_PATH.exists():
        load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)


def _get_str(name: str, default: str) -> str:
    """
    读取字符串型配置。

    入参：
    - name    : 环境变量名。
    - default : 环境变量缺失或为空白字符串时使用的默认值。
    返回：
    - 去除首尾空白后的字符串。
    """
    raw = os.getenv(name)
    if raw is None:
        return default

    normalized = raw.strip()
    return normalized if normalized else default


def _get_optional_str(name: str) -> str | None:
    """
    读取可选字符串型配置，缺失时返回 None。

    用于 ``OPENAI_BASE_URL`` 这类「不配置就走 SDK 默认值」的场景，
    不能用空字符串代替 None，否则会把 SDK 的默认 base_url 覆盖成非法值。
    """
    raw = os.getenv(name)
    if raw is None:
        return None

    normalized = raw.strip()
    return normalized or None


def _get_int(name: str, default: int) -> int:
    """
    读取整数型配置。

    异常：
    - 值无法转换为整数时抛出 ValueError，并在消息中带上变量名，便于快速定位配置错误。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，当前值：{raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    """
    读取浮点型配置。

    异常：
    - 值无法转换为浮点数时抛出 ValueError，并在消息中带上变量名。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是数字，当前值：{raw!r}") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    """
    运行期配置集合。

    字段分为四组：OpenAI 相关、数据库相关、去重策略相关、审计相关。
    """

    # ---------- OpenAI ----------
    # OpenAI API Key。必填，缺失时在 load_settings() 中直接报错。
    openai_api_key: str
    # 自定义 API 网关地址。为 None 时使用 OpenAI SDK 的官方默认地址。
    openai_base_url: str | None
    # 用于记忆提取、分类、精炼、摘要、判重的对话模型。
    llm_model: str
    # 用于生成摘要向量的 Embedding 模型。
    embedding_model: str
    # Embedding 维度。必须与 memory.embedding 列的 VECTOR(n) 定义严格一致。
    embedding_dim: int

    # ---------- PostgreSQL ----------
    # psycopg 连接字符串。
    pg_dsn: str

    # ---------- 去重策略 ----------
    # 向量召回的候选条数。
    dedup_top_k: int
    # 余弦距离上限。超过该距离的候选直接视为不相似，不再消耗大模型调用。
    dedup_max_distance: float

    # ---------- 审计 ----------
    # 写入 created_by / updated_by 的操作者标识。
    operator: str

    # ---------- 摘要 ----------
    # 摘要最大字符数。受 memory.summary 的 VARCHAR(128) 限制，默认按需求取 100。
    summary_max_chars: int


def load_settings() -> Settings:
    """
    读取环境变量并构造 Settings。

    异常：
    - 缺少 OPENAI_API_KEY 时抛出 ValueError，避免带着空 Key 一路跑到调用大模型时才失败。
    - 数值型配置格式错误时抛出 ValueError。
    """
    _load_env_file()

    api_key = _get_str("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError(
            f"未配置 OPENAI_API_KEY，请在 {ENV_FILE_PATH} 中补充该项，可参考 .env.example。"
        )

    return Settings(
        openai_api_key=api_key,
        openai_base_url=_get_optional_str("OPENAI_BASE_URL"),
        llm_model=_get_str("THOTH_LLM_MODEL", "gpt-4o-mini"),
        embedding_model=_get_str("THOTH_EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_dim=_get_int("THOTH_EMBEDDING_DIM", 1536),
        pg_dsn=_get_str(
            "THOTH_PG_DSN",
            "postgresql://thoth:123456@localhost:12001/thoth_memory",
        ),
        dedup_top_k=_get_int("THOTH_DEDUP_TOP_K", 5),
        dedup_max_distance=_get_float("THOTH_DEDUP_MAX_DISTANCE", 0.35),
        operator=_get_str("THOTH_OPERATOR", "THOTH_EXTRACTOR"),
        summary_max_chars=_get_int("THOTH_SUMMARY_MAX_CHARS", 100),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    获取全局唯一的 Settings 实例。

    使用 lru_cache 做单例，保证一次进程生命周期内配置只解析一次、且前后一致。
    单元测试中如需重新加载，可调用 ``get_settings.cache_clear()``。
    """
    return load_settings()
