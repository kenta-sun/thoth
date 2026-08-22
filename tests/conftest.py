"""
pytest 全局配置。

这里只做一件事：把 thoth 的日志打到控制台。
这批测试的目的之一是人工观察提取过程，而流水线的每一步判定都是通过日志输出的，
不开日志就只能看到最终结果，看不到中间过程。
"""

from __future__ import annotations

import logging
import sys

import pytest


@pytest.fixture(autouse=True)
def enable_thoth_logging():
    """
    自动应用的 fixture：为每个测试打开 thoth 的 DEBUG 日志。

    实现说明：
    - 只给 ``thoth`` 这个顶层 logger 挂 handler，不动 root logger，
      避免把第三方库的日志也一并放出来。
    - 每个测试结束后移除 handler 并还原级别，防止重复挂载导致日志成倍输出。
    """
    thoth_logger = logging.getLogger("thoth")
    previous_level = thoth_logger.level

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter("    [%(levelname)s] %(name)s - %(message)s"))

    thoth_logger.addHandler(handler)
    thoth_logger.setLevel(logging.DEBUG)

    yield

    thoth_logger.removeHandler(handler)
    thoth_logger.setLevel(previous_level)
