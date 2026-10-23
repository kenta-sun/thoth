"""DAO 层的单词表 SQL 映射：查询及写入返回实体，事务和业务判断由 Service 管理。"""

from __future__ import annotations

import psycopg
from psycopg.rows import class_row
from types import MappingProxyType

from thoth.entity import WordEntity, WordTagEntity
from thoth.common.query_words import TEXT_FIELDS, QUERY_OPERATORS
from thoth.dto.query_words import QueryRequest, QuerySqlSpec, QueryWordResult, SqlField
from thoth.utils.sql_query_builder import build_query


# 主表固定排除删除记录；统计按需 LEFT JOIN，缺失行在所有表达式中统一按零处理。
# 标签通过相关子查询投影、EXISTS 筛选，均不扩大主表行数，LIMIT 仍按单词计数。
WORD_QUERY_SPEC = QuerySqlSpec(
    source="word_tbl AS w", predicate="w.status_code <> 'D'",
    fields=MappingProxyType({
        **{name: SqlField(f"w.{name}", QUERY_OPERATORS[name]) for name in TEXT_FIELDS},
        "tags": SqlField(
            "ARRAY(SELECT wt.tag_code FROM word_tag_tbl AS wt WHERE wt.word_id = w.id ORDER BY wt.tag_code)",
            QUERY_OPERATORS["tags"], sortable=False,
            membership_expression="EXISTS (SELECT 1 FROM word_tag_tbl AS ft WHERE ft.word_id = w.id AND ft.tag_code = ANY({value}))",
        ),
        "usage_count": SqlField("COALESCE(u.usage_count, 0)", QUERY_OPERATORS["usage_count"], joins=("usage",)),
        "miss_count": SqlField("COALESCE(m.miss_count, 0)", QUERY_OPERATORS["miss_count"], joins=("miss",)),
    }),
    joins=MappingProxyType({
        "usage": "LEFT JOIN word_usage_tbl AS u ON u.word_id = w.id AND u.user_id = %(user_id)s",
        "miss": "LEFT JOIN word_miss_tbl AS m ON m.word_id = w.id AND m.user_id = %(user_id)s",
    }),
)


def _query_row_factory(cursor):
    """将动态投影列映射到各表实体，不用动态字典承载数据库记录。"""
    columns = tuple(column.name for column in cursor.description)

    def make_row(values) -> QueryWordResult:
        """依据已选列构造关联结果；未查询的实体字段保持 None。"""
        result = QueryWordResult()
        for name, value in zip(columns, values, strict=True):
            if name == "tags":
                result.tags = [WordTagEntity(tag_code=code) for code in value]
            elif name == "usage_count":
                result.usage.usage_count = value
            elif name == "miss_count":
                result.miss.miss_count = value
            else:
                setattr(result.word, name, value)
        return result

    return make_row


class WordTblMapper:
    """封装 word_tbl 的参数化 SQL 调用，不提交事务或判断业务操作。"""

    def __init__(self, connection: psycopg.Connection) -> None:
        """复用 Service 的连接，审计字段由 SQL 使用 CURRENT_USER 填充。"""
        self._connection = connection

    def query_words(self, request: QueryRequest, *, user_id: int) -> list[QueryWordResult]:
        """执行构建器生成的只读查询；不加行锁、不提交事务，空结果返回空列表。

        user_id 由 Service 查找已存在的用户取得，限定两张统计表的关联范围。
        request 已由 Service 校验；构建器再次约束字段及操作，参数交给驱动绑定。
        """
        query = build_query(request, WORD_QUERY_SPEC)
        query.params["user_id"] = user_id
        with self._connection.cursor(row_factory=_query_row_factory) as cursor:
            cursor.execute(query.sql, query.params)
            return cursor.fetchall()

    def find_existing_words(self, words: list[str]) -> list[WordEntity]:
        """按原文查询包含已删除状态的单词；空列表不查询，不加锁，驱动异常向上传递。"""
        if not words:
            return []
        # 按 word 原文一次查询本批已有记录，包含已标记删除的词；不加行锁，
        # 因此结果只反映查询时的存在性，保存时仍需处理并发新增或外部删除。
        sql = """
        SELECT id, word, common_form, hiragana, meaning, status_code
        FROM word_tbl
        WHERE word = ANY(%(words)s)
        """
        # class_row 按结果列名构造实体，字段值由驱动完成数据库类型适配。
        with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
            cursor.execute(sql, {"words": words})
            return cursor.fetchall()

    def insert(self, entity: WordEntity) -> WordEntity | None:
        """在调用方事务内新增；返回含生成 ID 和状态的业务实体，word 冲突时返回 None；其他驱动异常向上传递。"""
        # 写入业务字段，审计账号使用 CURRENT_USER，id、状态和时间交给数据库默认值生成。
        # word 的唯一约束配合 ON CONFLICT 避免并发新增时覆盖原记录；
        # RETURNING 返回实际新增的业务字段，发生冲突而未写入时不返回记录。
        sql = """
        INSERT INTO word_tbl (word, common_form, hiragana, meaning, created_by, updated_by)
        VALUES (%(word)s, %(common_form)s, %(hiragana)s, %(meaning)s, CURRENT_USER, CURRENT_USER)
        ON CONFLICT (word) DO NOTHING
        RETURNING id, word, common_form, hiragana, meaning, status_code
        """
        with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
            cursor.execute(sql, self._parameters(entity))
            return cursor.fetchone()

    def find_by_word_for_update(self, word: str) -> WordEntity | None:
        """按原文查询并锁定单词；不存在返回 None，锁由调用方事务持有至结束。

        包含已删除记录，由 Service 判断状态；行锁防止统计期间修改状态或删除。
        """
        sql = """
        SELECT id, word, common_form, hiragana, meaning, status_code
        FROM word_tbl WHERE word = %(word)s FOR UPDATE
        """
        with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
            cursor.execute(sql, {"word": word})
            return cursor.fetchone()

    def update(self, entity: WordEntity) -> WordEntity | None:
        """按 word 更新并锁行；None 信息字段保留原值，零行更新返回 None，由 Service 判断。"""
        # 只按 word 定位并更新三个信息字段及修改审计字段，不修改 word 或状态。
        # COALESCE 把请求中的 None 视为“保留当前数据库值”，避免清空原值，
        # 也避免使用批量查询时的旧实体覆盖其他请求刚修改的字段。
        # UPDATE 由数据库取得行锁；RETURNING 用于取得实际结果并识别零行更新。
        sql = """
        UPDATE word_tbl
        SET common_form = COALESCE(%(common_form)s, common_form),
            hiragana = COALESCE(%(hiragana)s, hiragana),
            meaning = COALESCE(%(meaning)s, meaning),
            updated_at = CURRENT_TIMESTAMP,
            updated_by = CURRENT_USER
        WHERE word = %(word)s
        RETURNING id, word, common_form, hiragana, meaning, status_code
        """
        with self._connection.cursor(row_factory=class_row(WordEntity)) as cursor:
            cursor.execute(sql, self._parameters(entity))
            return cursor.fetchone()

    def _parameters(self, entity: WordEntity) -> dict[str, str | None]:
        """在 SQL 绑定处读取业务字段，保留 None，不绑定 ID、状态及时间。"""
        return {
            "word": entity.word,
            "common_form": entity.common_form,
            "hiragana": entity.hiragana,
            "meaning": entity.meaning,
        }
