"""标签 SQL 生成工具：从公共目录生成初始化文件，仅显式运行时写文件，不连接数据库。"""

import argparse
from pathlib import Path

from thoth.common.tags import TAG_DEFINITIONS


def _literal(value: str) -> str:
    """转义标签常量为 PostgreSQL E 字符串，保留名称中的引号和反斜杠。"""
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def render_tag_sql() -> str:
    """生成插入缺失标签的 SQL；冲突时保留数据库已有名称，不删除标签。"""
    values = ",\n".join(
        "    (" + ", ".join(_literal(value) for value in (tag.code, tag.zh_name, tag.jp_name)) + ")"
        for tag in TAG_DEFINITIONS
    )
    return (
        "-- 自动生成：来源 thoth.common.tags.TAG_DEFINITIONS，请勿手工修改。\n"
        "-- 前置表：tag_tbl；仅插入缺失编码，保留已有记录。\n\n"
        "INSERT INTO tag_tbl (code, zh_name, jp_name)\nVALUES\n"
        + values + "\nON CONFLICT (code) DO NOTHING;\n"
    )


def main() -> None:
    """解析目标路径并生成文件；--check 只比较内容，文件缺失或过期时返回非零退出码。"""
    parser = argparse.ArgumentParser(description="从公共标签常量生成初始化 SQL，不执行 SQL。")
    parser.add_argument("--output", type=Path, default=Path("sql/dml/dml__tag_tbl.sql"))
    parser.add_argument("--check", action="store_true", help="只检查生成文件是否与常量一致")
    args = parser.parse_args()
    content = render_tag_sql()
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != content:
            parser.exit(1, "标签初始化 SQL 缺失或过期，请重新生成。\n")
    else:
        args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
