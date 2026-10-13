"""真实数据库验收：在专用测试库隔离 schema 中重建并验证跨用户统计隔离。"""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import json

import psycopg
from psycopg import sql
import pytest

from tests.integration.test_word_stats_postgres import _load_test_dsn, _connect_test_database
from thoth.service import (query_users_service, query_words_service, add_update_words_service,
                          count_word_usage_service, count_word_miss_service, reset_word_miss_service)
from thoth.common.tags import TAG_DEFINITIONS
from thoth.dto.request.query_words_request import WordQueryInput
from thoth.dto.request.add_update_words_request import WordWriteInput
from thoth.tools import query_words_tools, add_update_words_tools, query_users_tools

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def rebuilt(monkeypatch):
    """执行交付脚本并隔离全部服务连接；结束后清理本测试创建的 schema。"""
    dsn = _load_test_dsn(ROOT)
    schema = "thoth_users_test_" + uuid4().hex
    with _connect_test_database(dsn) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            admin.execute((ROOT / "sql/rebuild_all.sql").read_text())

            @contextmanager
            def connect(settings=None):
                """将真实业务连接限制在已核实的测试库和本次 schema。"""
                with _connect_test_database(dsn) as connection:
                    connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                    connection.execute("SET statement_timeout = '10s'")
                    yield connection

            for service in (query_users_service, query_words_service, add_update_words_service,
                            count_word_usage_service, count_word_miss_service, reset_word_miss_service):
                monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(operator="integration"))
                monkeypatch.setattr(service, "open_connection", connect)
            yield connect
        finally:
            admin.execute("ROLLBACK")
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def seed(connect):
    """通过 SQL 手动建测试用户，再通过 MCP Service 创建共享词条。"""
    with connect() as connection:
        connection.execute("INSERT INTO user_tbl (username) VALUES ('甲'), ('乙')")
    payload = [{"word": word, "common_form": word, "hiragana": "かな", "meaning": "释义", "tags": ["n"]}
               for word in ("a", "b")]
    result = add_update_words_tools.add_update_words(username="甲", words=[WordWriteInput.model_validate(item) for item in payload]).model_dump(mode="json")
    assert all(row["status"] == "created" for row in result["results"])


def query(username, **raw):
    """返回指定用户在共享词库中的查询结果。"""
    return query_words_tools.query_words(username=username, query=WordQueryInput.model_validate(raw)).model_dump(mode="json")["results"]


def test_rebuild_empty_tables_and_seed_dictionaries(rebuilt):
    assert query_users_tools.query_users().model_dump(mode="json") == {"results": []}
    with rebuilt() as connection:
        for table in ("user_tbl", "word_tbl", "word_tag_tbl", "word_usage_tbl", "word_miss_tbl"):
            assert connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone() == (0,)
        assert connection.execute("SELECT code FROM word_sts_tbl ORDER BY code").fetchall() == [("A",), ("D",)]
        assert connection.execute("SELECT count(*) FROM tag_tbl").fetchone() == (len(TAG_DEFINITIONS),)


def test_two_users_share_words_but_not_counts_or_reset(rebuilt):
    seed(rebuilt)
    assert query_users_tools.query_users().model_dump(mode="json") == {"results": [{"username": "甲"}, {"username": "乙"}]}
    for _ in range(3):
        count_word_miss_service.count_word_miss(['a'], "甲")
    count_word_usage_service.count_word_usage(['a'], "甲")
    assert query("乙", fields=["word", "usage_count", "miss_count"]) == [
        {"word": "a", "usage_count": 0, "miss_count": 0}, {"word": "b", "usage_count": 0, "miss_count": 0}]
    with rebuilt() as connection:
        assert connection.execute("SELECT count(*) FROM word_miss_tbl WHERE user_id=2").fetchone() == (0,)
    count_word_miss_service.count_word_miss(['b'], "乙")
    count_word_usage_service.count_word_usage(['b'], "乙")
    for field in ("miss_count", "usage_count"):
        assert query("甲", fields=["word"], sort=[{"field": field, "direction": "desc"}], limit=1) == [{"word": "a"}]
        assert query("乙", fields=["word"], sort=[{"field": field, "direction": "desc"}], limit=1) == [{"word": "b"}]
        assert query("乙", fields=["word"], where={field: {"gte": 1}}) == [{"word": "b"}]
    reset_word_miss_service.reset_word_miss(['a', 'b'], "乙")
    assert query("甲", fields=["miss_count"], where={"word": {"eq": "a"}}) == [{"miss_count": 3}]
    assert query("乙", fields=["miss_count"], where={"word": {"eq": "b"}}) == [{"miss_count": 0}]
    update = [WordWriteInput(word="a", meaning="共享的新释义", tags=["v"], action="update")]
    add_update_words_tools.add_update_words(username="乙", words=update)
    assert query("甲", fields=["meaning", "tags"], where={"word": {"eq": "a"}}) == [{"meaning": "共享的新释义", "tags": ["v"]}]


def test_user_and_statistics_constraints(rebuilt):
    seed(rebuilt)
    with rebuilt() as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute("INSERT INTO user_tbl (username) VALUES ('甲')")
        for username in ("", " a", "a\t", "\u3000a", "a\u00a0", "\x1ca"):
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute("INSERT INTO user_tbl (username) VALUES (%s)", (username,))
        with pytest.raises(psycopg.errors.StringDataRightTruncation):
            connection.execute("INSERT INTO user_tbl (username) VALUES (%s)", ("a" * 129,))
        connection.execute("INSERT INTO user_tbl (username) VALUES ('Alice'), ('alice')")
        for table in ("word_miss_tbl", "word_usage_tbl"):
            insert = sql.SQL("INSERT INTO {} (user_id,word_id) VALUES (%s,1)").format(sql.Identifier(table))
            connection.execute(insert, (1,))
            connection.execute(insert, (2,))
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(insert, (1,))
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                connection.execute(insert, (999,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute("DELETE FROM user_tbl WHERE id=1")


def test_rebuild_removes_old_data_and_reinitializes(rebuilt):
    seed(rebuilt)
    count_word_miss_service.count_word_miss(['a'], "甲")
    with rebuilt() as connection:
        connection.execute((ROOT / "sql/rebuild_all.sql").read_text())
        assert connection.execute("SELECT count(*) FROM word_tbl").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM user_tbl").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM tag_tbl").fetchone() == (len(TAG_DEFINITIONS),)


def test_external_dependency_rolls_back_whole_rebuild(rebuilt):
    seed(rebuilt)
    count_word_miss_service.count_word_miss(['a'], "甲")
    with rebuilt() as connection:
        connection.execute("CREATE VIEW retained_words AS SELECT word FROM word_tbl")
        with pytest.raises(psycopg.errors.DependentObjectsStillExist):
            connection.execute((ROOT / "sql/rebuild_all.sql").read_text())
        connection.execute("ROLLBACK")
        # 统计表在词表之前删除，回滚须连同已删除的表和数据一起恢复。
        assert connection.execute("SELECT miss_count FROM word_miss_tbl").fetchall() == [(1,)]
        assert connection.execute("SELECT count(*) FROM retained_words").fetchone() == (2,)
