"""验证集成测试配置优先级及写入前的数据库隔离检查，不连接真实数据库。"""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from tests.integration import test_word_stats_postgres as integration


@pytest.mark.parametrize("value", ["", "  process-test-dsn  "])
def test_process_setting_prevents_file_read(monkeypatch, value):
    """显式环境变量即使为空也优先，不读取本地配置。"""
    monkeypatch.setenv("THOTH_TEST_PG_DSN", value)
    reader = Mock(side_effect=AssertionError("不应读取文件"))
    monkeypatch.setattr(integration, "dotenv_values", reader)
    assert integration._load_test_dsn(Path("project")) == value.strip()
    reader.assert_not_called()


@pytest.mark.parametrize("values,expected", [
    ({"THOTH_TEST_PG_DSN": " file-test-dsn "}, "file-test-dsn"),
    ({"THOTH_PG_DSN": "business-dsn"}, ""),
])
def test_file_uses_only_test_connection(monkeypatch, values, expected):
    """缺少进程配置时仅取文件中的测试连接，不使用业务连接。"""
    monkeypatch.delenv("THOTH_TEST_PG_DSN", raising=False)
    reader = Mock(return_value=values)
    monkeypatch.setattr(integration, "dotenv_values", reader)
    assert integration._load_test_dsn(Path("project")) == expected
    reader.assert_called_once_with(Path("project/.env"))


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
