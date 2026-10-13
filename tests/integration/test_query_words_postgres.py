"""真实 PostgreSQL 查询验收：使用专用测试库的独立 schema，验证关联和 LIKE 原生行为。"""

import json

import pytest

from tests.integration.test_word_stats_postgres import database
from thoth.service import query_words_service as service


@pytest.fixture
def query_database(database, monkeypatch):
    """在隔离 schema 准备缺失统计、多标签、删除状态及含通配符的单词。"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    with database() as connection:
        for table in ("tag_tbl", "word_tag_tbl"):
            connection.execute((root / f"sql/ddl/ddl__create_table__{table}.sql").read_text())
        connection.execute((root / "sql/dml/dml__tag_tbl.sql").read_text())
        connection.execute("UPDATE word_tbl SET common_form=CASE word WHEN 'a' THEN '食べる' ELSE '食事' END")
        connection.execute("""
            INSERT INTO word_tbl (word, common_form, hiragana, meaning, status_code) VALUES
            ('c','食う','くう','吃','A'), ('d','学校','がっこう','学校','A'),
            ('literal','a%b_c','かな','字面通配符','A'), ('deleted','食べる','たべる','吃','D')
        """)
        connection.execute("""
            INSERT INTO word_tag_tbl (word_id, tag_code)
            SELECT w.id, t.code FROM word_tbl w CROSS JOIN tag_tbl t
            WHERE (w.word='a' AND t.code IN ('v','v2')) OR (w.word='c' AND t.code='v2')
               OR (w.word IN ('b','d') AND t.code='n') OR (w.word='deleted' AND t.code='v')
        """)
        connection.execute("""
            INSERT INTO word_usage_tbl (user_id, word_id, usage_count)
            SELECT 1, id, CASE word WHEN 'b' THEN 3 WHEN 'd' THEN 1 ELSE 0 END
            FROM word_tbl WHERE word IN ('b','c','d')
        """)
        connection.execute("""
            INSERT INTO word_miss_tbl (user_id, word_id, miss_count)
            SELECT 1, id, CASE word WHEN 'a' THEN 4 WHEN 'c' THEN 2 ELSE 9 END
            FROM word_tbl WHERE word IN ('a','c','d')
        """)
    monkeypatch.setattr(service, "open_connection", database)
    monkeypatch.setattr(service, "get_settings", lambda: None)
    return database


def query(raw):
    """调用真实查询 Service 并返回对象列表。"""
    return service.query_words(json.dumps(raw), username="tester")["results"]


def test_defaults_and_projection_do_not_write_statistics(query_database):
    with query_database() as connection:
        before = [connection.execute(f"SELECT * FROM {table} ORDER BY word_id").fetchall()
                  for table in ("word_usage_tbl", "word_miss_tbl")]
    rows = query({})
    assert [row["word"] for row in rows] == ["a", "b", "c", "d", "literal"]
    assert rows[0] == {"word": "a", "common_form": "食べる", "hiragana": "a", "meaning": "a",
                       "tags": ["v", "v2"], "usage_count": 0, "miss_count": 4}
    assert rows[1]["miss_count"] == 0 and rows[-1]["tags"] == []
    assert query({"fields": ["common_form"], "limit": 1}) == [{"common_form": "食べる"}]
    assert query({"where": {"word": "deleted"}}) == []
    assert query({"where": {"word": {"in": ["missing", "a"]}}, "fields": ["word"]}) == [{"word": "a"}]
    assert query({"where": {"word": "'; DROP TABLE word_tbl; --"}}) == []
    with query_database() as connection:
        after = [connection.execute(f"SELECT * FROM {table} ORDER BY word_id").fetchall()
                 for table in ("word_usage_tbl", "word_miss_tbl")]
    assert after == before


def test_ranking_missing_statistics_and_range_filters(query_database):
    assert query({"fields": ["word"], "sort": [["usage_count", "asc"]], "limit": 2}) == [
        {"word": "a"}, {"word": "c"}]
    assert query({"fields": ["word"], "sort": [["usage_count", "desc"]], "limit": 2}) == [
        {"word": "b"}, {"word": "d"}]
    assert query({"fields": ["word"], "sort": [["miss_count", "desc"]], "limit": 2}) == [
        {"word": "d"}, {"word": "a"}]
    assert query({"fields": ["word"], "where": {"usage_count": {"gte": 0, "lte": 0}},
                  "sort": [["usage_count", "asc"], ["miss_count", "desc"]]}) == [
        {"word": "a"}, {"word": "c"}, {"word": "literal"}]
    assert query({"fields": ["word"], "where": {"miss_count": {"in": [0]}}}) == [
        {"word": "b"}, {"word": "literal"}]


def test_tag_membership_has_no_duplicates_or_implicit_hierarchy(query_database):
    assert query({"fields": ["word"], "where": {"tags": {"in": ["v", "v2"]}}, "limit": 2}) == [
        {"word": "a"}, {"word": "c"}]
    assert query({"fields": ["word"], "where": {"tags": {"in": ["v"]}}}) == [{"word": "a"}]
    assert query({"fields": ["word"], "where": {"tags": {"in": ["unknown"]}}}) == []
    assert query({"fields": ["word"], "where": {
        "tags": {"in": ["v", "n"]}, "usage_count": {"lte": 1}, "miss_count": {"gte": 4}},
        "sort": [["miss_count", "desc"]], "limit": 1}) == [{"word": "d"}]


@pytest.mark.parametrize("pattern,words", [
    ("食%", ["a", "b", "c"]), ("%る", ["a"]), ("%食%", ["a", "b", "c"]),
    ("食_", ["b", "c"]), ("食べる", ["a"]), ("", []),
    (r"a\%b\_c", ["literal"]), ("%'; SELECT 1; --%", []),
])
def test_native_like_patterns(query_database, pattern, words):
    assert query({"fields": ["word"], "where": {"common_form": {"like": pattern}}}) == [
        {"word": word} for word in words]


def test_like_combines_with_in_and_unprojected_sort(query_database):
    assert query({"fields": ["common_form"], "where": {
        "common_form": {"in": ["食事", "食う", "学校"], "like": "食%"}},
        "sort": [["usage_count", "desc"]]}) == [{"common_form": "食事"}, {"common_form": "食う"}]
