"""
最小可用的 MCP Server 示例（基于 FastMCP）。

设计目标：
1. 仅暴露两个工具：update_memory 与 query_memory。
2. 两个工具都只接收一个字符串参数：text。
3. update_memory：将输入文本写入本地记忆文件，并返回更新内容。
4. query_memory：当前 demo 固定返回写死字符串（与 text 无关），但仍保留解析与异常处理流程。
5. 尽量避免向 stdout 打印调试信息，防止干扰 MCP 协议通讯。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# 记忆文件路径：放在当前脚本同目录，便于本地演示和排查。
MEMORY_FILE_PATH = Path(__file__).with_name("memory_store.json")

# query_memory 的写死返回内容（按需求固定返回，不做动态查询）。
FIXED_QUERY_RESPONSE = "这是一个写死的记忆查询结果（demo）"

# 初始化 MCP 服务实例；name 会显示在 MCP 客户端工具列表中。
mcp = FastMCP(name="thoth-memory-demo")


def parse_update_text(text: str) -> str:
    """
    解析 update_memory 的输入文本。

    处理策略：
    - 确保入参类型为字符串（理论上 FastMCP 已做基础校验，这里再做防御式校验）。
    - 去掉首尾空白字符，避免把纯空白文本写入记忆。
    - 解析失败时抛出 ValueError，由工具层统一转成友好错误信息。
    """
    if not isinstance(text, str):
        raise ValueError("update_memory 的参数 text 必须是字符串。")

    normalized = text.strip()
    if not normalized:
        raise ValueError("update_memory 的参数 text 不能为空。")

    return normalized


def parse_query_text(text: str) -> str:
    """
    解析 query_memory 的输入文本。

    说明：
    - 当前 demo 虽然返回固定字符串，但依然对输入做基础解析，
      这样后续替换为真实逻辑时无需改接口行为。
    """
    if not isinstance(text, str):
        raise ValueError("query_memory 的参数 text 必须是字符串。")

    normalized = text.strip()
    if not normalized:
        raise ValueError("query_memory 的参数 text 不能为空。")

    return normalized


def load_memory() -> dict[str, Any]:
    """
    从本地 JSON 文件加载记忆数据。

    异常友好处理：
    - 文件不存在：返回默认空结构，不报错。
    - JSON 损坏：抛出 ValueError，提示文件格式异常。
    - 数据结构非法（不是对象）：抛出 ValueError。
    """
    if not MEMORY_FILE_PATH.exists():
        return {}

    try:
        raw_data = MEMORY_FILE_PATH.read_text(encoding="utf-8")
        parsed = json.loads(raw_data)
    except json.JSONDecodeError as exc:
        raise ValueError("记忆文件 JSON 格式损坏，无法解析。") from exc
    except OSError as exc:
        raise ValueError(f"读取记忆文件失败：{exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("记忆文件内容结构非法，必须是 JSON 对象。")

    return parsed


def save_memory(memory_data: dict[str, Any]) -> None:
    """
    将记忆数据保存到本地 JSON 文件。

    处理策略：
    - 使用 ensure_ascii=False，便于直接保存中文文本。
    - 出错时抛出 ValueError，让工具层返回友好提示。
    """
    try:
        serialized = json.dumps(memory_data, ensure_ascii=False, indent=2)
        MEMORY_FILE_PATH.write_text(serialized + "\n", encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"写入记忆文件失败：{exc}") from exc


def set_memory(text: str) -> str:
    """
    写入记忆内容，并返回本次更新文本。

    当前 demo 仅保存最后一次写入值到 key: latest_update。
    """
    memory_data = load_memory()
    memory_data["latest_update"] = text
    save_memory(memory_data)
    return text


def get_memory(_query_text: str) -> str:
    """
    查询记忆内容。

    注意：
    - 按当前需求，返回固定写死字符串。
    - 仍保留函数分层，方便未来接入真实检索逻辑。
    """
    return FIXED_QUERY_RESPONSE


@mcp.tool
def update_memory(text: str) -> str:
    """
    MCP 工具：更新记忆。

    入参：
    - text: 一段自然语言文本。
    返回：
    - 本次 update 的文本内容（字符串）。
    """
    try:
        parsed_text = parse_update_text(text)
        return set_memory(parsed_text)
    except ValueError as exc:
        # 统一返回友好错误，避免抛出原始堆栈到协议层。
        return f"update_memory 执行失败：{exc}"


@mcp.tool
def query_memory(text: str) -> str:
    """
    MCP 工具：查询记忆。

    入参：
    - text: 一段自然语言文本（当前 demo 仅做校验，不参与查询）。
    返回：
    - 固定写死字符串。
    """
    try:
        parsed_text = parse_query_text(text)
        return get_memory(parsed_text)
    except ValueError as exc:
        return f"query_memory 执行失败：{exc}"


if __name__ == "__main__":
    # 使用 stdio 传输，便于被 Cursor MCP 直接拉起并通信。
    # 关闭 banner，减少非协议输出，避免干扰客户端解析。
    # 将日志级别压到 ERROR，减少普通 INFO 输出污染标准输出的风险。
    mcp.run(transport="stdio", show_banner=False, log_level="ERROR")
