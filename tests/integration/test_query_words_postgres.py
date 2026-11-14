"""真实 PostgreSQL 查询验收：使用专用测试库的独立 schema，验证关联和 LIKE 原生行为。"""

import json

import pytest

from tests.integration.test_word_stats_postgres import database
from thoth.service import query_words_service as service
from thoth.dto.request.query_words_request import WordQueryInput
from thoth.tools.query_words_tools import query_words


@pytest.fixture
def query_database(database, monkeypatch):
    """在隔离 schema 准备缺失统计、多标签、删除状态及含通配符的单词。"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    with database() as connection:
        for table in ("tag_tbl", "word_tag_tbl", "word_fam_tbl"):
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
            INSERT INTO word_count_tbl (user_id, word_id, count_type, count_value)
            SELECT 1, id, 'usage', CASE word WHEN 'b' THEN 3 WHEN 'd' THEN 1 ELSE 0 END
            FROM word_tbl WHERE word IN ('b','c','d')
        """)
        connection.execute("""
            INSERT INTO word_count_tbl (user_id, word_id, count_type, count_value)
            SELECT 1, id, 'miss', CASE word WHEN 'a' THEN 4 WHEN 'c' THEN 2 ELSE 9 END
            FROM word_tbl WHERE word IN ('a','c','d')
        """)
    monkeypatch.setattr(service, "open_connection", database)
    monkeypatch.setattr(service, "get_settings", lambda: None)
    return database


def query(raw):
    """调用真实查询 Service 并返回对象列表。"""
    return query_words(username="tester", query=WordQueryInput.model_validate(raw)).model_dump(mode="json")["results"]


def test_defaults_and_projection_do_not_write_statistics(query_database):
    with query_database() as connection:
        before = [connection.execute("SELECT * FROM word_count_tbl WHERE user_id=1 AND count_type=%s ORDER BY word_id", (kind,)).fetchall()
                  for kind in ("usage", "miss")]
    rows = sorted(query({}), key=lambda row: row["word"])
    assert [row["word"] for row in rows] == ["a", "b", "c", "d", "literal"]
    assert rows[0] == {"word": "a", "common_form": "食べる", "hiragana": "a", "meaning": "a",
                       "tags": ["v", "v2"], "fam": "fam_new", "usage_count": 0, "miss_count": 4}
    assert rows[1]["miss_count"] == 0 and rows[-1]["tags"] == []
    assert query({"fields": ["common_form"], "sort": [{"field": "word", "direction": "asc"}], "limit": 1}) == [{"common_form": "食べる"}]
    assert query({"where": {"word": {"eq": "deleted"}}}) == []
    assert query({"where": {"word": {"in": ["missing", "a"]}}, "fields": ["word"]}) == [{"word": "a"}]
    assert query({"where": {"word": {"eq": "'; DROP TABLE word_tbl; --"}}}) == []
    with query_database() as connection:
        after = [connection.execute("SELECT * FROM word_count_tbl WHERE user_id=1 AND count_type=%s ORDER BY word_id", (kind,)).fetchall()
                 for kind in ("usage", "miss")]
    assert after == before


def test_ranking_missing_statistics_and_range_filters(query_database):
    assert query({"fields": ["word"], "sort": [{"field": "usage_count", "direction": "asc"}, {"field": "word", "direction": "asc"}], "limit": 2}) == [
        {"word": "a"}, {"word": "c"}]
    assert query({"fields": ["word"], "sort": [{"field": "usage_count", "direction": "desc"}], "limit": 2}) == [
        {"word": "b"}, {"word": "d"}]
    assert query({"fields": ["word"], "sort": [{"field": "miss_count", "direction": "desc"}], "limit": 2}) == [
        {"word": "d"}, {"word": "a"}]
    assert query({"fields": ["word"], "where": {"usage_count": {"gte": 0, "lte": 0}},
                  "sort": [{"field": "usage_count", "direction": "asc"}, {"field": "miss_count", "direction": "desc"}]}) == [
        {"word": "a"}, {"word": "c"}, {"word": "literal"}]
    assert sorted(query({"fields": ["word"], "where": {"miss_count": {"in": [0]}}}), key=lambda row: row["word"]) == [
        {"word": "b"}, {"word": "literal"}]


def test_tag_membership_has_no_duplicates_or_implicit_hierarchy(query_database):
    assert sorted(query({"fields": ["word"], "where": {"tags": {"in": ["v", "v2"]}}, "limit": 2}), key=lambda row: row["word"]) == [
        {"word": "a"}, {"word": "c"}]
    assert query({"fields": ["word"], "where": {"tags": {"in": ["v"]}}}) == [{"word": "a"}]
    assert query({"fields": ["word"], "where": {"tags": {"in": ["unknown"]}}}) == []
    assert query({"fields": ["word"], "where": {
        "tags": {"in": ["v", "n"]}, "usage_count": {"lte": 1}, "miss_count": {"gte": 4}},
        "sort": [{"field": "miss_count", "direction": "desc"}], "limit": 1}) == [{"word": "d"}]


@pytest.mark.parametrize("pattern,words", [
    ("食%", ["a", "b", "c"]), ("%る", ["a"]), ("%食%", ["a", "b", "c"]),
    ("食_", ["b", "c"]), ("食べる", ["a"]), ("", []),
    (r"a\%b\_c", ["literal"]), ("%'; SELECT 1; --%", []),
])
def test_native_like_patterns(query_database, pattern, words):
    assert sorted(query({"fields": ["word"], "where": {"common_form": {"like": pattern}}}), key=lambda row: row["word"]) == [
        {"word": word} for word in words]


def test_like_combines_with_in_and_unprojected_sort(query_database):
    assert query({"fields": ["common_form"], "where": {
        "common_form": {"in": ["食事", "食う", "学校"], "like": "食%"}},
        "sort": [{"field": "usage_count", "direction": "desc"}]}) == [{"common_form": "食事"}, {"common_form": "食う"}]


def test_random_selection_respects_filter_limit_and_uniqueness(query_database):
    """验证真实 SQL 抽样范围与条数，不用概率性断言要求两次顺序不同。"""
    raw = {"fields": ["word"], "where": {"tags": {"in": ["v", "v2", "n"]}},
           "sort": [{"field": "random"}], "limit": 3}
    rows = query(raw)
    words = [row["word"] for row in rows]
    assert len(words) == len(set(words)) == 3
    assert set(words) <= {"a", "b", "c", "d"}
    rows = query({**raw, "limit": 100})
    assert len(rows) == 4 and {row["word"] for row in rows} == {"a", "b", "c", "d"}
    rows = query({"fields": ["word", "miss_count"], "sort": [
        {"field": "miss_count", "direction": "desc"}, {"field": "random"}]})
    assert [row["miss_count"] for row in rows] == [9, 4, 2, 0, 0]


def test_fam_defaults_user_isolation_combination_and_read_only(query_database):
    """未评定与显式 new 同时命中；其他用户不影响结果，查询不创建默认记录。"""
    with query_database() as connection:
        connection.execute("""
            INSERT INTO word_fam_tbl (user_id, word_id, tag_code)
            SELECT 1, id, CASE word WHEN 'a' THEN 'fam_new' WHEN 'c' THEN 'fam_rep' ELSE 'fam_ok' END
            FROM word_tbl WHERE word IN ('a','c','d','deleted')
        """)
        connection.execute("INSERT INTO word_fam_tbl (user_id, word_id, tag_code) SELECT 2, id, 'fam_ok' FROM word_tbl WHERE word='b'")
        before = connection.execute('SELECT * FROM word_fam_tbl ORDER BY user_id, word_id').fetchall()
    rows = query({'fields': ['word', 'fam'], 'where': {'fam': {'in': ['fam_new']}},
                  'sort': [{'field': 'word', 'direction': 'asc'}]})
    assert rows == [{'word': word, 'fam': 'fam_new'} for word in ('a', 'b', 'literal')]
    assert query({'fields': ['word', 'tags', 'fam', 'miss_count'],
                  'where': {'fam': {'in': ['fam_new', 'fam_rep', 'fam_new']},
                            'tags': {'in': ['v', 'v2']}, 'miss_count': {'gte': 2}},
                  'sort': [{'field': 'miss_count', 'direction': 'desc'}], 'limit': 1}) == [
        {'word': 'a', 'tags': ['v', 'v2'], 'fam': 'fam_new', 'miss_count': 4}]
    assert query({'fields': ['word'], 'where': {'fam': {'in': ['fam_ok']}}}) == [{'word': 'd'}]
    other = query_words(username='other', query=WordQueryInput.model_validate(
        {'fields': ['word', 'fam'], 'where': {'fam': {'in': ['fam_ok']}}})).model_dump(mode='json')['results']
    assert other == [{'word': 'b', 'fam': 'fam_ok'}]
    assert query({'fields': ['fam'], 'where': {'word': {'eq': 'literal'}}}) == [{'fam': 'fam_new'}]
    assert query({'where': {'fam': {'in': ['fam_inf']}}}) == []
    with query_database() as connection:
        assert connection.execute('SELECT * FROM word_fam_tbl ORDER BY user_id, word_id').fetchall() == before


@pytest.mark.parametrize('code,message', [('not_exists', '标签不存在'), ('v', '类型不符')])
def test_fam_invalid_tag_returns_tool_error(query_database, code, message):
    """字典不存在或标签类型错误由 Service 转为工具错误，不返回误导性的空结果。"""
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match=message):
        query({'where': {'fam': {'in': [code]}}})
