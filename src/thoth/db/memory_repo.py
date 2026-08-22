"""
记忆数据访问层。

职责：把 memory / memory_version 两张表的 SQL 操作集中收拢，
让业务层完全不出现 SQL 语句。

当前提供两个能力：
1. ``search_similar_by_embedding()``：按摘要向量做相似度召回，用于判重取候选。
2. ``create_memory()``              ：在一个事务里写入 memory 与 memory_version。

表结构参见 sql/ddl/ 下的建表语句。
"""

from __future__ import annotations

import psycopg
from pgvector import Vector

from thoth.db.connection import DatabaseError
from thoth.models import CandidateMemory

# 记忆状态编码，取值来自 memory_status 字典表（见 sql/dml/dml__memory_status.sql）。
# A=ACTIVE / I=INACTIVE / E=EXPIRED / D=DELETED。
# 本模块只用到 ACTIVE：新记忆一律以 ACTIVE 写入，召回也只看 ACTIVE。
STATUS_ACTIVE = "A"

# 相似记忆召回。
# 说明：
# - 只召回 ACTIVE 的记忆，已停用/过期/删除的记忆不参与判重。
# - 距离运算符 <=> 为 pgvector 的余弦距离，与建表时创建的
#   idx_memory_embedding_hnsw (vector_cosine_ops) 索引匹配，可以走索引。
# - SELECT 与 ORDER BY 使用同一个命名参数，psycopg 会复用同一个绑定值。
_SQL_SEARCH_SIMILAR = """
SELECT id,
       summary,
       embedding <=> %(query_vector)s AS distance
FROM memory
WHERE current_status = %(status)s
ORDER BY embedding <=> %(query_vector)s
LIMIT %(top_k)s
"""

# 写入记忆单元。embedding 存的是摘要向量，与 memory.embedding 的列注释一致。
_SQL_INSERT_MEMORY = """
INSERT INTO memory (embedding, summary, current_status, created_by, updated_by)
VALUES (%(embedding)s, %(summary)s, %(status)s, %(operator)s, %(operator)s)
RETURNING id
"""

# 写入记忆正文的首个版本。
_SQL_INSERT_MEMORY_VERSION = """
INSERT INTO memory_version (memory_id, content, version_status, created_by, updated_by)
VALUES (%(memory_id)s, %(content)s, %(status)s, %(operator)s, %(operator)s)
RETURNING id
"""


class MemoryRepository:
    """
    记忆仓储。

    一个实例绑定一条数据库连接，由调用方负责连接的生命周期
    （通常通过 ``thoth.db.open_connection()`` 的上下文管理器）。
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        """
        入参：
        - connection : 已经完成 pgvector 类型注册的连接。
        """
        self._connection = connection

    def search_similar_by_embedding(
        self,
        embedding: list[float],
        top_k: int,
    ) -> list[CandidateMemory]:
        """
        按摘要向量召回最相似的若干条已有记忆。

        入参：
        - embedding : 待写入记忆的摘要向量。
        - top_k     : 召回条数上限。

        返回：
        - 候选记忆列表，按余弦距离升序（越靠前越相似）。库里没有 ACTIVE 记忆时返回空列表。

        异常：
        - ValueError   ：top_k 非正数。
        - DatabaseError：查询失败。

        说明：本方法只负责「召回」，不做任何相似/不相似的判定。
        距离阈值过滤与最终判重分别由 deduplicator 与大模型负责。
        """
        if top_k <= 0:
            raise ValueError(f"top_k 必须为正整数，当前值：{top_k}")

        params = {
            # 必须包成 pgvector 的 Vector 类型：pgvector 只为 Vector 与 numpy.ndarray
            # 注册了 dumper，直接传 Python list 会被 psycopg 当成数组类型而报错。
            "query_vector": Vector(embedding),
            "status": STATUS_ACTIVE,
            "top_k": top_k,
        }

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(_SQL_SEARCH_SIMILAR, params)
                rows = cursor.fetchall()
        except psycopg.Error as exc:
            # 查询失败同样要回滚，否则连接会停留在失败事务中，后续语句全部报错。
            self._connection.rollback()
            raise DatabaseError(f"召回相似记忆失败：{exc}") from exc

        return [
            CandidateMemory(memory_id=row[0], summary=row[1], distance=float(row[2]))
            for row in rows
        ]

    def create_memory(
        self,
        *,
        summary: str,
        embedding: list[float],
        content: str,
        operator: str,
    ) -> tuple[int, int]:
        """
        写入一条新记忆，包含 memory 主表与 memory_version 正文版本表。

        入参：
        - summary   : 记忆摘要，写入 memory.summary。
        - embedding : 摘要向量，写入 memory.embedding。
        - content   : 精炼后的记忆正文，写入 memory_version.content。
        - operator  : 操作者标识，写入两张表的 created_by / updated_by。

        返回：
        - (memory_id, memory_version_id) 二元组。

        异常：
        - DatabaseError：写入失败。此时事务已回滚，两张表都不会留下半条数据。

        事务边界说明：
        本方法内部提交。这样同一批次里后写入的记忆在做向量召回时
        能看到前面刚写入的记忆，批内互相重复的情况会被自然覆盖。
        """
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    _SQL_INSERT_MEMORY,
                    {
                        "embedding": Vector(embedding),
                        "summary": summary,
                        "status": STATUS_ACTIVE,
                        "operator": operator,
                    },
                )
                memory_row = cursor.fetchone()
                if memory_row is None:
                    raise DatabaseError("写入 memory 表后未能取回自增主键。")
                memory_id = int(memory_row[0])

                cursor.execute(
                    _SQL_INSERT_MEMORY_VERSION,
                    {
                        "memory_id": memory_id,
                        "content": content,
                        "status": STATUS_ACTIVE,
                        "operator": operator,
                    },
                )
                version_row = cursor.fetchone()
                if version_row is None:
                    raise DatabaseError("写入 memory_version 表后未能取回自增主键。")
                version_id = int(version_row[0])

            self._connection.commit()
        except psycopg.Error as exc:
            self._connection.rollback()
            raise DatabaseError(f"写入记忆失败：{exc}") from exc
        except DatabaseError:
            self._connection.rollback()
            raise

        return memory_id, version_id
