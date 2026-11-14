"""真实 PostgreSQL 验证：从环境或项目配置读取专用测试 DSN，使用临时 schema。"""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from thoth.common.config import load_settings
from thoth.dao.word_tbl_mapper import WordTblMapper
from thoth.dao.word_count_tbl_mapper import WordCountTblMapper
from thoth.entity import WordCountEntity
from thoth.tools.word_stats_mapping import to_stats_results
from thoth.service import count_word_usage_service, count_word_miss_service, reset_word_miss_service


def call_stats(service, name, words, username="tester"):
    """调用真实统计服务并通过响应子模型检查对外结果。"""
    return {"results": [row.model_dump(mode="json") for row in
                        to_stats_results(getattr(service, name)(words, username))]}


def _load_test_dsn(root):
    """只读取显式指定的 .env.test；配置缺失时不回退正式配置。"""
    return load_settings(config_file=root / ".env.test").pg_dsn


@contextmanager
def _connect_test_database(dsn):
    """连接并只读确认实际库名，拒绝在 thoth_test 以外的数据库执行测试。"""
    try:
        connection = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    except psycopg.Error:
        # 驱动异常可能包含连接信息，失败时不展示 DSN 或原始异常。
        raise pytest.fail.Exception(
            "无法连接 PostgreSQL 测试库，请检查地址、端口、认证和执行环境权限。", pytrace=False
        ) from None
    with connection:
        if connection.execute("SELECT current_database()").fetchone() != ("thoth_test",):
            pytest.fail("集成测试仅允许连接 thoth_test，已拒绝执行写入。", pytrace=False)
        yield connection


@pytest.fixture
def database(monkeypatch):
    """在显式提供的测试库建立独立 schema，结束时只删除该 schema。"""
    root = Path(__file__).resolve().parents[2]
    dsn = _load_test_dsn(root)
    schema = "thoth_stats_test_" + uuid4().hex
    with _connect_test_database(dsn) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            for table in ("user_tbl", "word_sts_tbl", "word_tbl", "count_type_tbl", "word_count_tbl"):
                admin.execute((root / f"sql/ddl/ddl__create_table__{table}.sql").read_text())
            for table in ("word_sts_tbl", "count_type_tbl"):
                admin.execute((root / f"sql/dml/dml__{table}.sql").read_text())
            admin.execute("INSERT INTO user_tbl (username) VALUES ('tester'), ('other')")
            admin.execute("INSERT INTO word_tbl (word, common_form, hiragana, meaning) VALUES ('a','a','a','a'),('b','b','b','b')")

            @contextmanager
            def connect(settings=None):
                """每次调用使用独立连接，限制锁等待和语句时间，隔离测试 schema。"""
                with _connect_test_database(dsn) as connection:
                    connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                    connection.execute("SET statement_timeout = '10s'")
                    yield connection

            for service in (count_word_usage_service, count_word_miss_service, reset_word_miss_service):
                monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace())
                monkeypatch.setattr(service, "open_connection", connect)
            yield connect
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


CASES = [(count_word_usage_service, "count_word_usage", "usage"),
         (count_word_miss_service, "count_word_miss", "miss")]


def count_miss():
    """完整错误计数调用。"""
    return call_stats(count_word_miss_service, "count_word_miss", ['a'], username="tester")["results"][0]


def reset():
    """完整清零调用。"""
    return call_stats(reset_word_miss_service, "reset_word_miss", ['a'], username="tester")["results"][0]


@pytest.mark.parametrize("service,name,kind", CASES)
def test_overlapping_concurrent_batches(database, service, name, kind):
    workers = 8
    barrier = Barrier(workers)

    def increment(index):
        barrier.wait(timeout=10)
        return call_stats(service, name, ["a", "b"] if index % 2 else ["b", "a"], username="tester")["results"]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        batches = list(executor.map(increment, range(workers)))
    assert all(row["status"] == "updated" for batch in batches for row in batch)
    with database() as connection:
        query = "SELECT count_value FROM word_count_tbl WHERE user_id=1 AND count_type=%s ORDER BY word_id"
        assert connection.execute(query, (kind,)).fetchall() == [(workers,), (workers,)]


@pytest.mark.parametrize("service,name,kind", CASES)
def test_failed_batch_preserves_zero_initialization(database, service, name, kind):
    with database() as connection:
        connection.execute("INSERT INTO word_count_tbl (user_id, word_id, count_type, count_value) SELECT 1, id, %s, 9223372036854775807 FROM word_tbl WHERE word='a'", (kind,))
    rows = call_stats(service, name, ['b', 'a', None, 'missing'], username="tester")["results"]
    assert [row["status"] for row in rows] == ["failed", "failed", "skipped", "skipped"]
    assert all("counts" not in row for row in rows)
    with database() as connection:
        values = connection.execute("SELECT word, count_value FROM word_count_tbl JOIN word_tbl ON id=word_id WHERE user_id=1 AND count_type=%s ORDER BY word", (kind,)).fetchall()
        assert values == [("a", 9223372036854775807), ("b", 0)]


@pytest.mark.parametrize("first", ["reset", "count"])
def test_reset_and_count_follow_row_lock_order(database, first):
    assert count_miss()["counts"] == {"miss_count": 1}
    with ThreadPoolExecutor(max_workers=1) as executor, database() as connection:
        with connection.transaction():
            word = WordTblMapper(connection).find_by_word_for_update("a")
            mapper = WordCountTblMapper(connection)
            entity = WordCountEntity(user_id=1, word_id=word.id, count_type="miss", updated_by="test")
            if first == "reset":
                mapper.find_for_update(word.id, user_id=1, count_type="miss")
                mapper.reset(entity)
                future = executor.submit(count_miss)
            else:
                mapper.increment_many([entity], user_id=1, count_type="miss")
                future = executor.submit(reset)
        result = future.result(timeout=15)
    assert result["counts"] == {"miss_count": 1 if first == "reset" else 0}


def test_reset_noop_preserves_audit_and_usage(database):
    assert reset()["status"] == "skipped"
    with database() as connection:
        assert connection.execute("SELECT count(*) FROM word_count_tbl WHERE user_id=1 AND count_type='miss'").fetchone() == (0,)
    assert count_miss()["counts"] == {"miss_count": 1}
    assert call_stats(count_word_usage_service, "count_word_usage", ['a'], username="tester")["results"][0]["counts"] == {"usage_count": 1}
    assert reset()["counts"] == {"miss_count": 0}
    with database() as connection:
        before = connection.execute("SELECT * FROM word_count_tbl WHERE user_id=1 AND count_type='miss'").fetchone()
    assert reset()["status"] == "skipped"
    with database() as connection:
        assert connection.execute("SELECT * FROM word_count_tbl WHERE user_id=1 AND count_type='miss'").fetchone() == before
        assert connection.execute("SELECT count_value FROM word_count_tbl WHERE user_id=1 AND count_type='usage'").fetchone() == (1,)


@pytest.mark.parametrize("stage", ["before_initialize", "before_update"])
def test_status_change_during_batch_is_not_reported_success(database, monkeypatch, stage):
    method = "initialize_many" if stage == "before_initialize" else "increment_many"
    original = getattr(WordCountTblMapper, method)

    def change_status(self, entities, *, user_id, count_type):
        with database() as connection:
            connection.execute("UPDATE word_tbl SET status_code='D' WHERE word='a'")
        return original(self, entities, user_id=user_id, count_type=count_type)

    monkeypatch.setattr(WordCountTblMapper, method, change_status)
    row = count_miss()
    assert row["status"] == "skipped" and "counts" not in row
    with database() as connection:
        values = connection.execute("SELECT count_value FROM word_count_tbl WHERE user_id=1 AND count_type='miss'").fetchall()
        assert values == ([] if stage == "before_initialize" else [(0,)])


def test_initialization_preserves_existing_audit(database):
    assert count_miss()["status"] == "updated"
    with database() as connection:
        before = connection.execute("SELECT * FROM word_count_tbl WHERE user_id=1 AND count_type='miss'").fetchone()
        WordCountTblMapper(connection).initialize_many([WordCountEntity(user_id=1, word_id=before[1], count_type="miss")], user_id=1, count_type="miss")
        assert connection.execute("SELECT * FROM word_count_tbl WHERE user_id=1 AND count_type='miss'").fetchone() == before


def test_count_key_constraints_and_delete_policies(database):
    """同一用户单词允许不同类型，重复三元键及非法计数被拒绝，删除策略保持。"""
    with database() as connection:
        insert = "INSERT INTO word_count_tbl (user_id, word_id, count_type) VALUES (%s, %s, %s)"
        for key in ((1, 1, 'miss'), (1, 1, 'usage'), (2, 1, 'miss'), (1, 2, 'miss')):
            connection.execute(insert, key)
        assert connection.execute("SELECT count_value FROM word_count_tbl").fetchall() == [(0,)] * 4
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(insert, (1, 1, 'miss'))
        for key in ((999, 1, 'miss'), (1, 999, 'miss'), (1, 1, 'unknown')):
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                connection.execute(insert, key)
        for value, error in ((-1, psycopg.errors.CheckViolation), (None, psycopg.errors.NotNullViolation)):
            with pytest.raises(error):
                connection.execute("UPDATE word_count_tbl SET count_value=%s WHERE user_id=1 AND word_id=1 AND count_type='miss'", (value,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute("DELETE FROM user_tbl WHERE id=1")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute("DELETE FROM count_type_tbl WHERE code='miss'")
        connection.execute("DELETE FROM word_tbl WHERE id=1")
        assert connection.execute("SELECT user_id, word_id, count_type FROM word_count_tbl").fetchall() == [(1, 2, 'miss')]


def test_concurrent_users_and_types_remain_isolated(database):
    """并发累计同一单词的两类计数及两个用户，清零只影响选中的用户和类型。"""
    barrier = Barrier(4)

    def increment(task):
        """各任务独立执行指定次数，使用不同期望值识别串写或丢失更新。"""
        username, service, name, count = task
        barrier.wait(timeout=10)
        for _ in range(count):
            assert call_stats(service, name, ['a'], username)["results"][0]["status"] == "updated"

    tasks = [
        ('tester', count_word_miss_service, 'count_word_miss', 2),
        ('tester', count_word_usage_service, 'count_word_usage', 3),
        ('other', count_word_miss_service, 'count_word_miss', 4),
        ('other', count_word_usage_service, 'count_word_usage', 5),
    ]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(increment, tasks))
    with database() as connection:
        query = "SELECT user_id, word_id, count_type, count_value FROM word_count_tbl ORDER BY user_id, word_id, count_type"
        assert connection.execute(query).fetchall() == [(1, 1, 'miss', 2), (1, 1, 'usage', 3), (2, 1, 'miss', 4), (2, 1, 'usage', 5)]
    assert reset()["counts"] == {"miss_count": 0}
    with database() as connection:
        assert connection.execute(query).fetchall() == [(1, 1, 'miss', 0), (1, 1, 'usage', 3), (2, 1, 'miss', 4), (2, 1, 'usage', 5)]
