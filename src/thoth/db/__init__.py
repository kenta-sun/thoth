"""
数据访问子包：PostgreSQL + pgvector。

对外暴露：
- ``MemoryRepository``：记忆相关的全部 SQL 操作入口。
- ``open_connection`` ：创建并初始化（注册 vector 类型）好的数据库连接。
"""

from thoth.db.connection import open_connection
from thoth.db.memory_repo import MemoryRepository

__all__ = ["MemoryRepository", "open_connection"]
