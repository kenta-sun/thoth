"""数据库基础层：提供 PostgreSQL 连接管理，具体表读写由 DAO 负责。"""

from thoth.db.connection import open_connection

__all__ = ["open_connection"]
