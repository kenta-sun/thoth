"""验证 Docker 单配置文件的覆盖、隔离和缓存边界，不访问真实配置或数据库。"""

import os

import pytest

from thoth.common import config
from tests.integration import test_word_stats_postgres as integration


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """准备虚构正式配置，并隔离进程变量及服务配置缓存。"""
    monkeypatch.delenv("THOTH_PG_DSN", raising=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    path = tmp_path / ".env.prd"
    path.write_text("THOTH_PG_DSN=postgresql://user:password@invalid.test/custom_live\n")
    config.get_settings.cache_clear()
    yield path
    config.get_settings.cache_clear()


def test_file_configuration(config_file):
    """单个文件即可提供全部业务配置，无需公共文件或环境名。"""
    settings = config.load_settings(config_file=config_file)
    assert settings.pg_dsn.endswith("/custom_live")


def test_process_values_override_file(config_file, monkeypatch):
    """进程变量可以覆盖文件值，不需要引入其他配置层。"""
    monkeypatch.setenv("THOTH_PG_DSN", "process-dsn")
    settings = config.load_settings(config_file=config_file)
    assert settings.pg_dsn == "process-dsn"


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_process_connection_does_not_fall_back(config_file, monkeypatch, value):
    """显式空进程连接串拒绝运行，不回退文件内的有效值。"""
    monkeypatch.setenv("THOTH_PG_DSN", value)
    with pytest.raises(ValueError, match="未配置 THOTH_PG_DSN"):
        config.load_settings(config_file=config_file)


def test_missing_file_fails_even_with_process_connection(config_file, monkeypatch):
    """显式指定的配置文件缺失时必须报错，暴露部署遗漏。"""
    config_file.unlink()
    monkeypatch.setenv("THOTH_PG_DSN", "process-dsn")
    with pytest.raises(ValueError, match="缺少配置文件"):
        config.load_settings(config_file=config_file)


def test_process_only_configuration_does_not_read_files(config_file, monkeypatch):
    """未指定文件的内部调用只读取进程变量。"""
    monkeypatch.setenv("THOTH_PG_DSN", "process-dsn")
    def forbidden(*args, **kwargs):
        """禁止访问任何文件。"""
        pytest.fail("不得加载文件")
    monkeypatch.setattr(config, "dotenv_values", forbidden)
    assert config.load_settings().pg_dsn == "process-dsn"


def test_legacy_profiles_do_not_affect_service(config_file, monkeypatch):
    """旧公共文件、环境选择变量和目录变量均不影响服务配置。"""
    root = config_file.parent
    (root / ".env").write_text("THOTH_PG_DSN=wrong\nTHOTH_ENV=dev\n")
    (root / ".env.dev").write_text("THOTH_PG_DSN=wrong-dev\n")
    monkeypatch.setenv("THOTH_ENV", "dev")
    monkeypatch.setenv("THOTH_CONFIG_DIR", "/nonexistent")
    assert config.get_settings().pg_dsn.endswith("/custom_live")


def test_reading_is_independent_of_cwd(config_file, monkeypatch, tmp_path):
    """工作目录变化不改变服务读取的配置位置。"""
    monkeypatch.chdir(tmp_path.parent)
    assert config.get_settings().pg_dsn.endswith("/custom_live")


def test_configuration_does_not_mutate_environment(config_file):
    """加载文件不修改全局进程变量。"""
    before = dict(os.environ)
    config.load_settings(config_file=config_file)
    assert dict(os.environ) == before


def test_password_interpolation_is_disabled(config_file, monkeypatch):
    """密码中的变量样式字符按字面保留。"""
    config_file.write_text('THOTH_PG_DSN="postgresql://u:${OTHER}@invalid.test/custom_live"\n')
    monkeypatch.setenv("OTHER", "unexpected")
    assert "${OTHER}" in config.load_settings(config_file=config_file).pg_dsn


def test_configuration_cache(config_file):
    """修改文件不会改变已缓存配置，清除缓存后重新读取。"""
    assert config.get_settings().pg_dsn.endswith("/custom_live")
    config_file.write_text("THOTH_PG_DSN=changed\n")
    assert config.get_settings().pg_dsn.endswith("/custom_live")
    config.get_settings.cache_clear()
    assert config.get_settings().pg_dsn == "changed"


def test_integration_configuration_is_explicit_and_isolated(config_file, monkeypatch):
    """集成测试只读取测试文件，正式文件存在也不得作为回退。"""
    root = config_file.parent
    monkeypatch.setenv("THOTH_ENV", "prd")
    with pytest.raises(ValueError, match=".env.test"):
        integration._load_test_dsn(root)
    (root / ".env.test").write_text("THOTH_PG_DSN=postgresql://u:p@invalid.test/thoth_test\n")
    assert integration._load_test_dsn(root).endswith("/thoth_test")
