"""检查实体覆盖所有表及字段，并允许空构造、部分构造和后续赋值。"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from pathlib import Path
import re
from typing import get_type_hints

import pytest

from thoth.entities import (
    TagEntity,
    WordEntity,
    WordMissEntity,
    WordStatusEntity,
    WordTagEntity,
    WordUsageEntity,
)


DDL_DIRECTORY = Path(__file__).resolve().parents[2] / "sql" / "ddl"
TABLE_ENTITIES = {
    "word_tbl": WordEntity,
    "tag_tbl": TagEntity,
    "word_sts_tbl": WordStatusEntity,
    "word_tag_tbl": WordTagEntity,
    "word_usage_tbl": WordUsageEntity,
    "word_miss_tbl": WordMissEntity,
}
SQL_TYPES = {
    "BIGINT": int,
    "TEXT": str,
    "CHAR": str,
    "VARCHAR": str,
    "TIMESTAMPTZ": datetime,
}


def test_every_database_table_has_an_entity():
    tables = {
        match.group(1)
        for ddl in DDL_DIRECTORY.glob("*.sql")
        for match in re.finditer(r"CREATE TABLE\s+(\w+)", ddl.read_text())
    }

    assert tables == TABLE_ENTITIES.keys()


@pytest.mark.parametrize("table,entity", TABLE_ENTITIES.items())
def test_entity_fields_and_base_types_match_ddl(table, entity):
    ddl = (DDL_DIRECTORY / f"ddl__create_table__{table}.sql").read_text()
    expected = {}
    # 项目 DDL 将每个字段独占一行；实体允许 None，与数据库非空约束无关。
    for name, sql_type in re.findall(
        r"^\s+([a-z][a-z_0-9]*)\s+([A-Z]+(?:\(\d+\))?)[^\n]*$",
        ddl,
        re.MULTILINE,
    ):
        python_type = SQL_TYPES[sql_type.split("(")[0]]
        expected[name] = python_type | None

    assert expected
    assert get_type_hints(entity) == expected
    assert [field.name for field in fields(entity)] == list(expected)


@pytest.mark.parametrize("entity", TABLE_ENTITIES.values())
def test_entities_can_be_constructed_without_values(entity):
    record = entity()

    for field in fields(entity):
        assert getattr(record, field.name) is None


@pytest.mark.parametrize(
    "entity,values",
    [
        (WordEntity, {"word": "食べる"}),
        (TagEntity, {"zh_name": "动词"}),
        (WordStatusEntity, {"description": "正在使用"}),
        (WordTagEntity, {"tag_code": "verb"}),
        (WordUsageEntity, {"usage_count": 2}),
        (WordMissEntity, {"miss_count": 1}),
    ],
)
def test_entities_allow_partial_values_and_later_assignment(entity, values):
    record = entity(**values)

    for field in fields(entity):
        assert getattr(record, field.name) == values.get(field.name)

    record.updated_by = "test-operator"
    assert record.updated_by == "test-operator"
    record.updated_by = None
    assert record.updated_by is None
