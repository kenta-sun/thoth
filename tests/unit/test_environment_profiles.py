"""验证环境配置的选择、覆盖、失败边界与无全局副作用，不访问真实数据库。"""

import os

import pytest

from thoth.common import config
from tests.integration import test_word_stats_postgres as integration


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    """为三个环境准备独立配置，屏蔽宿主机的配置变量。"""
    for key in ("THOTH_ENV", "THOTH_PG_DSN", "THOTH_OPERATOR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text("THOTH_ENV=dev\nTHOTH_OPERATOR=common\n")
    for env, database in config.ENV_DATABASES.items():
        (tmp_path / f".env.{env}").write_text(
            f"THOTH_PG_DSN=postgresql://user:password@invalid.test/{database}\n"
        )
    config.get_settings.cache_clear()
    yield tmp_path
    config.get_settings.cache_clear()


@pytest.mark.parametrize("environment", ["dev", "test", "prd"])
def test_profile_selection(profiles, monkeypatch, environment):
    """进程环境覆盖公共文件的环境选择，并读取对应文件。"""
    monkeypatch.setenv("THOTH_ENV", environment)
    settings = config.load_settings()
    assert settings.environment == environment
    assert settings.pg_dsn.endswith("/" + config.ENV_DATABASES[environment])
    assert settings.expected_database == config.ENV_DATABASES[environment]


def test_configuration_precedence(profiles, monkeypatch):
    """环境文件覆盖公共值，进程值再覆盖环境文件。"""
    with (profiles / ".env.dev").open("a") as file:
        file.write("THOTH_OPERATOR=profile\n")
    assert config.load_settings().operator == "profile"
    monkeypatch.setenv("THOTH_OPERATOR", "process")
    monkeypatch.setenv("THOTH_PG_DSN", "process-dsn")
    assert config.load_settings().operator == "process"
    assert config.load_settings().pg_dsn == "process-dsn"


def test_explicit_test_selection_ignores_prd_choice(profiles, monkeypatch):
    """真实测试加载入口无视日常环境，仍读取测试配置。"""
    (profiles / ".env").write_text("THOTH_ENV=prd\n")
    monkeypatch.setenv("THOTH_ENV", "prd")
    assert integration._load_test_dsn(profiles).endswith("/thoth_test")


def test_switching_profiles_does_not_pollute_process(profiles):
    """连续读取环境不会修改进程变量，亦不会串用上次连接。"""
    before = dict(os.environ)
    assert config.load_settings("dev").pg_dsn.endswith("/thoth_dev")
    assert config.load_settings("test").pg_dsn.endswith("/thoth_test")
    assert config.load_settings("prd").pg_dsn.endswith("/thoth_memory")
    assert dict(os.environ) == before


@pytest.mark.parametrize("value", ["", "staging", "../prd", "DEV"])
def test_invalid_environment_does_not_fall_back(profiles, monkeypatch, value):
    """非法或显式为空的环境不得回退到公共文件中的 dev。"""
    monkeypatch.setenv("THOTH_ENV", value)
    with pytest.raises(ValueError, match="THOTH_ENV"):
        config.load_settings()


def test_missing_environment_is_error(profiles):
    """没有指定环境时禁止隐式默认到任何数据库。"""
    (profiles / ".env").write_text("")
    with pytest.raises(ValueError, match="THOTH_ENV"):
        config.load_settings()


def test_missing_profile_even_with_process_dsn_is_error(profiles, monkeypatch):
    """环境文件必须存在，进程连接值不绕过缺失文件检查。"""
    (profiles / ".env.prd").unlink()
    monkeypatch.setenv("THOTH_PG_DSN", "process-dsn")
    with pytest.raises(ValueError, match="缺少环境配置文件"):
        config.load_settings("prd")


@pytest.mark.parametrize("process_value", [None, "", "  "])
def test_missing_or_empty_dsn_fails(profiles, monkeypatch, process_value):
    """空连接不回退到其他配置源；缺少连接也明确报错。"""
    if process_value is None:
        (profiles / ".env.dev").write_text("")
    else:
        monkeypatch.setenv("THOTH_PG_DSN", process_value)
    with pytest.raises(ValueError, match="未配置 THOTH_PG_DSN"):
        config.load_settings()


def test_common_database_connection_is_rejected(profiles):
    """公共文件不得携带可能被其他环境继承的数据库凭证。"""
    with (profiles / ".env").open("a") as file:
        file.write("THOTH_PG_DSN=wrong-database\n")
    with pytest.raises(ValueError, match="公共 .env 不允许"):
        config.load_settings()


def test_only_selected_profile_is_read(profiles, monkeypatch):
    """开发启动不会读取生产配置文件。"""
    paths = []
    reader = config.dotenv_values

    def record(path, **kwargs):
        """记录读取路径，保留真实 dotenv 解析行为。"""
        paths.append(path.name)
        return reader(path, **kwargs)

    monkeypatch.setattr(config, "dotenv_values", record)
    config.load_settings()
    assert paths == [".env", ".env.dev"]


def test_password_like_interpolation_remains_literal(profiles, monkeypatch):
    """dotenv 不对含变量样式字符的密码执行隐式展开。"""
    (profiles / ".env.dev").write_text('THOTH_PG_DSN="postgresql://u:${OTHER}@invalid.test/thoth_dev"\n')
    monkeypatch.setenv("OTHER", "unexpected")
    assert "${OTHER}" in config.load_settings().pg_dsn


def test_settings_cache_requires_explicit_refresh(profiles, monkeypatch):
    """运行配置保持缓存，清除后才采用新环境。"""
    assert config.get_settings().environment == "dev"
    monkeypatch.setenv("THOTH_ENV", "test")
    assert config.get_settings().environment == "dev"
    config.get_settings.cache_clear()
    assert config.get_settings().environment == "test"
