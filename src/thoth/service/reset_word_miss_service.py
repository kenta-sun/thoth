"""reset_word_miss 专属服务：逐词锁定并清零已有错误计数，保留统计记录。"""

import psycopg

from thoth.service.user_lookup_service import validate_username, require_user
from thoth.common.config import get_settings
from thoth.dao.word_tbl_mapper import WordTblMapper
from thoth.dao.word_miss_tbl_mapper import WordMissTblMapper
from thoth.db.connection import DatabaseError, open_connection
from thoth.dto.word_stats import WordListItem, StatsResult
from thoth.entity import WordMissEntity
from thoth.service.word_stats_input_service import prepare_word_list, merge_stats_results, stats_database_error


def reset_word_miss(words: list[str], username: str) -> list[StatsResult]:
    """清零已有 miss_count，不操作 usage_count，不创建统计记录。

    Args:
        username: 已手动创建的用户名，精确匹配，不存在时抛出 ValueError。
        words: 单词列表；空数组允许，无效和重复元素跳过。

    Returns:
        按输入顺序返回逐项结果；不存在、已删除、无统计或已为零时跳过。

    Raises:
        ValueError: 单词列表或用户名非法，或用户不存在。
        DatabaseError: 配置或连接失败。
    """
    validate_username(username)
    preprocessed = prepare_word_list(words)
    settings = get_settings()
    with open_connection(settings) as connection:
        user = require_user(connection, username)
        executed = [
            _reset_item(item, connection, user.id)
            for item in preprocessed.pending_items
        ]
        return merge_stats_results(preprocessed, executed)


def _reset_item(item: WordListItem, connection: psycopg.Connection,
                user_id: int) -> StatsResult:
    """用独立事务锁定单词及计数后清零，提交后返回；数据库失败回滚并脱敏。

    user_id 限定统计归属；connection 必须无外层事务；item.index 为原始输入位置；仅实际更新时由数据库记录修改账号。
    """
    word = item.original_value
    index = item.index
    try:
        with connection.transaction():
            entity = WordTblMapper(connection).find_by_word_for_update(word)
            if entity is None or entity.status_code == "D":
                result = StatsResult(index, word, "skipped", "单词不存在。")
            else:
                if entity.id is None:
                    raise DatabaseError("单词记录未返回有效 ID。")
                mapper = WordMissTblMapper(connection)
                # 先锁行再判断，保证已为零时不修改审计字段，也不与其他更新交错。
                record = mapper.find_for_update(entity.id, user_id=user_id)
                if record is None:
                    result = StatsResult(index, word, "skipped", "尚无错误计数记录。")
                elif record.miss_count == 0:
                    result = StatsResult(index, word, "skipped", "错误计数已为零。", miss_count=0)
                else:
                    updated = mapper.reset(WordMissEntity(user_id=user_id, word_id=entity.id))
                    if updated is None or updated.miss_count != 0:
                        raise DatabaseError("清零未返回有效记录。")
                    result = StatsResult(index, word, "updated", miss_count=updated.miss_count)
        return result
    except (DatabaseError, psycopg.Error) as exc:
        error = stats_database_error(exc) if isinstance(exc, psycopg.Error) else exc
        return StatsResult(index, word, "failed", str(error))
