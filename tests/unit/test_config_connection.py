"""配置与连接生命周期测试；禁止读取本地配置或连接真实数据库。"""

from unittest.mock import Mock

import psycopg
import pytest

from thoth.common import config
from thoth.db import connection as connection_module


TEST_DSN = "postgresql://test_user:test_password@invalid.test/test_words"


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    """屏蔽本地配置读取，隔离进程环境，并在每个测试前后清空配置缓存。"""
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    monkeypatch.setenv("THOTH_PG_DSN", TEST_DSN)
    monkeypatch.delenv("THOTH_OPERATOR", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_settings_need_no_openai_configuration():
    settings = config.load_settings()

    assert settings.pg_dsn == TEST_DSN
    assert settings.operator == "THOTH_MCP"


@pytest.mark.parametrize("dsn", [None, "", " \t\n"])
def test_missing_or_empty_database_dsn_is_explicit_error(monkeypatch, dsn):
    if dsn is None:
        monkeypatch.delenv("THOTH_PG_DSN")
    else:
        monkeypatch.setenv("THOTH_PG_DSN", dsn)

    with pytest.raises(ValueError, match="未配置 THOTH_PG_DSN"):
        config.load_settings()


@pytest.mark.parametrize("operator", ["", " \t\n"])
def test_empty_operator_uses_default(monkeypatch, operator):
    monkeypatch.setenv("THOTH_OPERATOR", operator)

    assert config.load_settings().operator == "THOTH_MCP"


def test_configuration_trims_outer_whitespace(monkeypatch):
    monkeypatch.setenv("THOTH_PG_DSN", f" {TEST_DSN} \n")
    monkeypatch.setenv("THOTH_OPERATOR", "  vocabulary_writer \n")

    settings = config.load_settings()

    assert settings.pg_dsn == TEST_DSN
    assert settings.operator == "vocabulary_writer"


def test_operator_accepts_128_characters(monkeypatch):
    operator = "词" * 128
    monkeypatch.setenv("THOTH_OPERATOR", operator)

    assert config.load_settings().operator == operator


def test_operator_rejects_more_than_128_characters(monkeypatch):
    monkeypatch.setenv("THOTH_OPERATOR", "词" * 129)

    with pytest.raises(ValueError, match="THOTH_OPERATOR 不能超过 128 个字符"):
        config.load_settings()


def test_settings_repr_omits_connection_credentials():
    displayed = repr(config.load_settings())

    assert TEST_DSN not in displayed
    assert "test_password" not in displayed
    assert "pg_dsn" not in displayed
    assert "THOTH_MCP" in displayed


@pytest.fixture
def fake_connect(monkeypatch):
    """替换驱动连接函数，返回可检查调用参数和关闭次数的模拟对象。"""
    connect = Mock(return_value=Mock())
    monkeypatch.setattr(connection_module.psycopg, "connect", connect)
    return connect


@pytest.mark.parametrize("explicit_settings", [True, False])
def test_connection_uses_autocommit_and_closes(fake_connect, explicit_settings):
    settings = config.load_settings() if explicit_settings else None

    with connection_module.open_connection(settings) as opened:
        assert opened is fake_connect.return_value
        opened.close.assert_not_called()

    fake_connect.assert_called_once_with(
        TEST_DSN, autocommit=True, connect_timeout=5
    )
    opened.close.assert_called_once_with()


def test_connection_closes_when_caller_fails(fake_connect):
    with pytest.raises(ValueError, match="caller failed"):
        with connection_module.open_connection():
            raise ValueError("caller failed")

    fake_connect.return_value.close.assert_called_once_with()


def test_connection_error_does_not_echo_dsn_or_credentials(fake_connect):
    fake_connect.side_effect = psycopg.OperationalError(
        f"could not connect using {TEST_DSN}"
    )

    with pytest.raises(connection_module.DatabaseError) as captured:
        with connection_module.open_connection():
            pytest.fail("failed connection must not enter context body")

    message = str(captured.value)
    assert "连接 PostgreSQL 失败" in message
    assert "THOTH_PG_DSN" in message
    assert TEST_DSN not in message
    assert "test_password" not in message
