"""SQL 生成工具：按依赖顺序合并分表 DDL 和字典数据，不连接数据库。"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TABLES = ("user_tbl", "word_sts_tbl", "tag_tbl", "word_tbl", "word_tag_tbl", "word_fam_tbl", "count_type_tbl", "word_count_tbl")
OUTPUT = ROOT / "sql" / "rebuild_all.sql"
UPGRADE_OUTPUT = ROOT / "sql" / "manual" / "replace_word_statistics.sql"


def render_rebuild_sql() -> str:
    """返回单事务重建脚本；删除八张现用表及两张旧统计表，外部依赖存在时失败回滚。"""
    parts = ["""-- 警告：清空八张项目表的全部数据，包括用户、单词、标签关联、熟悉度和统计！
-- 重复执行也会再次清空数据；不迁移旧数据，不创建实际用户。
-- 同时删除旧版 word_miss_tbl、word_usage_tbl（如存在）。
-- 请先停止 MCP 并确认当前连接的目标库；完成后手动添加用户，再启动新版 MCP。
-- 由 python -m thoth.utils.generate_rebuild_sql 生成，源文件为分表 DDL 和字典 DML。
BEGIN;
"""]
    parts.extend(f"DROP TABLE IF EXISTS {table};\n" for table in ("word_miss_tbl", "word_usage_tbl"))
    parts.extend(f"DROP TABLE IF EXISTS {table};\n" for table in reversed(TABLES))
    parts.extend((ROOT / f"sql/ddl/ddl__create_table__{table}.sql").read_text() for table in TABLES)
    parts.extend((ROOT / f"sql/dml/dml__{table}.sql").read_text() for table in ("word_sts_tbl", "tag_tbl", "count_type_tbl"))
    parts.append("COMMIT;\n")
    return "\n".join(parts)


def render_upgrade_sql() -> str:
    """生成一次性统计表替换脚本，保留用户、单词及标签数据；不连接数据库。"""
    parts = ["""-- 一次性替换旧统计表：丢弃 miss、usage 旧计数，不迁移数据。
-- 保留用户、单词、标签及其他业务表；新统计表初始为空。
-- 停止旧版 MCP，确认目标库后整份执行；客户端报错须停止并 ROLLBACK。
-- 在单事务内创建新表和字典、删除旧表；外部依赖存在时失败回滚，不使用 CASCADE。
-- 不可重复执行；新表已存在时 CREATE TABLE 失败，避免清空已有新统计。
-- 由 python -m thoth.utils.generate_rebuild_sql 生成，勿单独维护合并内容。
BEGIN;
"""]
    parts.extend((ROOT / f"sql/ddl/ddl__create_table__{table}.sql").read_text()
                 for table in ("count_type_tbl", "word_count_tbl"))
    parts.append((ROOT / "sql/dml/dml__count_type_tbl.sql").read_text())
    parts.append("DROP TABLE word_miss_tbl;\nDROP TABLE word_usage_tbl;\nCOMMIT;\n")
    return "\n".join(parts)


def main() -> None:
    """生成重建与一次性替换脚本；--check 只检查两份产物，不连接数据库。"""
    parser = argparse.ArgumentParser(description="生成数据库重建和统计表替换脚本")
    parser.add_argument("--check", action="store_true", help="仅检查脚本是否与源文件一致")
    args = parser.parse_args()
    for output, expected in ((OUTPUT, render_rebuild_sql()), (UPGRADE_OUTPUT, render_upgrade_sql())):
        if args.check:
            if not output.exists() or output.read_text() != expected:
                raise SystemExit(f"{output.name} 与源文件不一致，请重新生成。")
        else:
            output.write_text(expected)


if __name__ == "__main__":
    main()
