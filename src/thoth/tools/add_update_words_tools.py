"""单词写入工具入口：将请求模型转换为内部指令，并映射保存结果与协议错误。"""

from typing import Annotated
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from thoth.db.connection import DatabaseError
from thoth.dto.request.add_update_words_request import WordWriteInput
from thoth.dto.response.add_update_words_response import AddUpdateWordsResponse, WordWriteResult
from thoth.dto.word import WordWriteCommand, WordBatchResult
from thoth.service import add_update_words_service

ADD_UPDATE_WORDS_DESCRIPTION = """新增或局部更新共享日语词库中的单词及标签。
每项独立事务；单项业务失败不影响其他项。同批重复 word 的所有项均失败。
按原文精确匹配已有词，包括已标记删除的记录，不改变单词原文或记录状态。
create 对已有词仍检查标签是否合法；update 对不存在的词按新增要求检查完整信息。
找不到合适已有标签时不要提交，不得编造或随意选择标签。
格式错误拒绝整批，业务结果按输入顺序返回。"""


def to_write_commands(words: list[WordWriteInput]) -> list[WordWriteCommand]:
    """显式提取业务字段，避免请求模型及其序列化约定进入 Service。"""
    return [WordWriteCommand(
        word=item.word, common_form=item.common_form, hiragana=item.hiragana,
        meaning=item.meaning, tags=tuple(item.tags), action=item.action,
    ) for item in words]


def to_write_response(batch: WordBatchResult) -> AddUpdateWordsResponse:
    """按原下标转换保存结果，None 可选字段由响应模型省略。"""
    return AddUpdateWordsResponse(results=[WordWriteResult(
        index=row.index, word=row.word, status=row.status, reason=row.reason,
        fields=list(row.fields) if row.fields is not None else None,
    ) for row in batch.results])


def add_update_words(
    words: Annotated[list[WordWriteInput], Field(min_length=1, description="待新增或更新的单词对象列表，至少一项；每项可独立指定 action。")],
) -> AddUpdateWordsResponse:
    """适配写入请求和响应；连接或整批业务失败转换为 MCP 工具错误。"""
    try:
        batch = add_update_words_service.add_update_words(to_write_commands(words))
        return to_write_response(batch)
    except (ValueError, DatabaseError) as exc:
        raise ToolError(str(exc)) from exc


def register(mcp: FastMCP) -> None:
    """注册写入工具，不读取配置或建立连接。"""
    mcp.tool(description=ADD_UPDATE_WORDS_DESCRIPTION)(add_update_words)
