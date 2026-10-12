"""count_word_usage 专属服务：过滤输入，批量定位、初始化及加一，按原位置返回。"""

from typing import Any

import psycopg
from fastmcp.exceptions import ToolError

from thoth.common.config import get_settings
from thoth.dao.word_tbl_mapper import WordTblMapper
from thoth.dao.word_usage_tbl_mapper import WordUsageTblMapper
from thoth.db.connection import DatabaseError, open_connection
from thoth.dto.word_stats import StatsResult
from thoth.entity import WordUsageEntity
from thoth.service.word_stats_input_service import parse_word_list_text, merge_stats_results, serialize_stats, stats_database_error


def count_word_usage(text: str) -> dict[str, list[dict[str, Any]]]:
    """批量为 usage_count 加一，不开启跨语句事务，也不自动重试。

    Args:
        text: 单词 JSON 字符串数组，空数组允许；无效和重复元素跳过。

    Returns:
        按输入位置返回结果；初始化或加一失败时待计数项全部 failed，过滤项不变。
        初始化成功而加一失败时允许保留零值记录。

    Raises:
        ToolError: 整批格式、配置、连接或初始查询失败。
    """
    try:
        preprocessed = parse_word_list_text(text)
        if preprocessed.status == "stop":
            raise ToolError(preprocessed.message)
        items = preprocessed.pending_items
        if not items:
            return serialize_stats(merge_stats_results(preprocessed, []))
        settings = get_settings()
        with open_connection(settings) as connection:
            # 一次查询定位全部有效词；不锁主表，写入时再次限定主表存在且未删除。
            words = [item.original_value for item in items]
            try:
                records = WordTblMapper(connection).find_existing_words(words)
            except psycopg.Error as exc:
                raise stats_database_error(exc) from exc
            existing = {record.word: record for record in records
                        if record.status_code != "D" and record.id is not None}
            pending = {item.index: existing[item.original_value] for item in items
                       if item.original_value in existing}
            results = {item.index: StatsResult(item.index, item.original_value, "skipped", "单词不存在。")
                       for item in items}
            if pending:
                mapper = WordUsageTblMapper(connection)
                entities = [WordUsageEntity(word_id=record.id) for record in pending.values()]
                try:
                    # 两条独立提交的批量写入；只有最终 RETURNING 中的记录算成功。
                    mapper.initialize_many(entities, operator=settings.operator)
                    updated = mapper.increment_many(entities, operator=settings.operator)
                    if any(record.usage_count is None for record in updated):
                        raise DatabaseError("批量计数未返回有效数值。")
                    by_id = {record.word_id: record for record in updated}
                    for index, word in pending.items():
                        record = by_id.get(word.id)
                        results[index] = (
                            StatsResult(index, word.word, "updated", usage_count=record.usage_count)
                            if record is not None else
                            StatsResult(index, word.word, "skipped", "记录在处理期间发生变化，未更新计数。")
                        )
                except (DatabaseError, psycopg.Error) as exc:
                    error = stats_database_error(exc) if isinstance(exc, psycopg.Error) else exc
                    for index, word in pending.items():
                        results[index] = StatsResult(index, word.word, "failed", str(error))
            return serialize_stats(merge_stats_results(preprocessed, list(results.values())))
    except (ValueError, DatabaseError) as exc:
        raise ToolError(str(exc)) from exc
