"""验证集成测试配置优先级及写入前的数据库隔离检查，不连接真实数据库。"""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from tests.integration import test_word_stats_postgres as integration


def test_test_entry_explicitly_selects_test(monkeypatch):
    """测试入口固定选择 test，不受生产环境选择影响。"""
    monkeypatch.setenv("THOTH_ENV", "prd")
    settings = Mock(pg_dsn="test-dsn")
    loader = Mock(return_value=settings)
    monkeypatch.setattr(integration, "load_settings", loader)
    assert integration._load_test_dsn(Path("project")) == "test-dsn"
    loader.assert_called_once_with(config_file=Path("project/.env.test"))


@pytest.mark.parametrize("database_name", ["thoth_memory", "postgres"])
def test_wrong_database_is_rejected_before_writes(monkeypatch, database_name):
    """实际连接目标不是测试库时，只读检查后关闭连接，不交给测试写入。"""
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (database_name,)
    monkeypatch.setattr(integration.psycopg, "connect", Mock(return_value=connection))
    with pytest.raises(pytest.fail.Exception, match="仅允许连接 thoth_test"):
        with integration._connect_test_database("test-dsn"):
            pytest.fail("不应允许进入写入阶段")
    connection.execute.assert_called_once_with("SELECT current_database()")
    connection.__exit__.assert_called_once()


def test_connection_failure_hides_driver_details(monkeypatch):
    """连接失败不会在异常链中展示驱动携带的连接信息。"""
    monkeypatch.setattr(integration.psycopg, "connect", Mock(
        side_effect=integration.psycopg.OperationalError("private-connection-details")
    ))
    with pytest.raises(pytest.fail.Exception) as captured:
        with integration._connect_test_database("test-dsn"):
            pytest.fail("失败连接不能进入测试")
    assert "private-connection-details" not in str(captured.value)
    assert captured.value.__suppress_context__ is True
