"""SQL 生成工具：按依赖顺序合并分表 DDL 和字典数据，不连接数据库。"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TABLES = ("user_tbl", "word_sts_tbl", "tag_tbl", "word_tbl", "word_tag_tbl", "word_usage_tbl", "word_miss_tbl")
OUTPUT = ROOT / "sql" / "rebuild_all.sql"


def render_rebuild_sql() -> str:
    """返回单事务重建脚本；只删除明确列出的七张表，外部依赖存在时失败回滚。"""
    parts = ["""-- 警告：清空七张项目表的全部数据，包括用户、单词、标签关联和统计！
-- 重复执行也会再次清空数据；不迁移旧数据，不创建实际用户。
-- 请先停止 MCP 并确认当前连接的目标库；完成后手动添加用户，再启动新版 MCP。
-- 由 python -m thoth.utils.generate_rebuild_sql 生成，源文件为分表 DDL 和字典 DML。
BEGIN;
"""]
    parts.extend(f"DROP TABLE IF EXISTS {table};\n" for table in reversed(TABLES))
    parts.extend((ROOT / f"sql/ddl/ddl__create_table__{table}.sql").read_text() for table in TABLES)
    parts.extend((ROOT / f"sql/dml/dml__{table}.sql").read_text() for table in ("word_sts_tbl", "tag_tbl"))
    parts.append("COMMIT;\n")
    return "\n".join(parts)


def main() -> None:
    """默认生成合并脚本；--check 仅检查一致性，不写入文件或访问数据库。"""
    parser = argparse.ArgumentParser(description="生成完整数据库重建脚本")
    parser.add_argument("--check", action="store_true", help="仅检查脚本是否与源文件一致")
    args = parser.parse_args()
    expected = render_rebuild_sql()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != expected:
            raise SystemExit("重建脚本与源文件不一致，请重新生成。")
    else:
        OUTPUT.write_text(expected)


if __name__ == "__main__":
    main()
