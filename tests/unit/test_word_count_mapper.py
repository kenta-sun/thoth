"""统一统计 Mapper 验证：绑定完整范围、空批次行为及两类计数的实体映射。"""

import pytest

from thoth.dao.word_count_tbl_mapper import WordCountTblMapper
from thoth.entity import WordCountEntity
from tests.unit.test_word_repository import ScriptedConnection
from thoth.utils.generate_rebuild_sql import UPGRADE_OUTPUT, render_upgrade_sql


@pytest.mark.parametrize("user_id", [1, 2])
@pytest.mark.parametrize("kind", ["miss", "usage", "inf_miss"])
def test_all_operations_bind_user_word_and_type(user_id, kind):
    """初始化、递增、锁定及清零均限定完整键，返回记录携带正确类型。"""
    connection = ScriptedConnection(None, [(user_id, 7, kind, 3)], (user_id, 7, kind, 3), (user_id, 7, kind, 0))
    mapper = WordCountTblMapper(connection)
    entity = WordCountEntity(user_id=user_id, word_id=7, count_type=kind)
    mapper.initialize_many([entity], user_id=user_id, count_type=kind)
    updated = mapper.increment_many([entity], user_id=user_id, count_type=kind)
    locked = mapper.find_for_update(7, user_id=user_id, count_type=kind)
    reset = mapper.reset(entity)
    assert [(row.user_id, row.word_id, row.count_type, row.count_value) for row in updated] == [(user_id, 7, kind, 3)]
    assert locked == updated[0]
    assert reset == WordCountEntity(user_id=user_id, word_id=7, count_type=kind, count_value=0)
    for index, (query, params) in enumerate(connection.statements):
        assert params['user_id'] == user_id and params['count_type'] == kind
        assert params.get('ids', [params.get('word_id')]) == [7]
        if index:
            assert 'user_id = %(user_id)s' in query
            assert 'count_type = %(count_type)s' in query
    assert 'ON CONFLICT (user_id, word_id, count_type) DO NOTHING' in connection.statements[0][0]
    assert connection.commits == connection.rollbacks == 0


def test_empty_batches_do_not_execute_sql():
    connection = ScriptedConnection()
    mapper = WordCountTblMapper(connection)
    assert mapper.initialize_many([], user_id=1, count_type='miss') is None
    assert mapper.increment_many([], user_id=1, count_type='usage') == []
    assert connection.statements == []


def test_upgrade_sql_matches_sources_and_only_drops_old_statistics():
    """一次性替换产物保持源文件一致，删除范围仅为两张旧统计表。"""
    script = render_upgrade_sql()
    assert UPGRADE_OUTPUT.read_text() == script
    drops = [line for line in script.splitlines() if line.startswith('DROP TABLE')]
    assert drops == ['DROP TABLE word_miss_tbl;', 'DROP TABLE word_usage_tbl;']
    assert '\nBEGIN;\n' in script and script.endswith('COMMIT;\n')
