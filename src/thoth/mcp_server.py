"""MCP 启动模块：加载统一注册的工具，并以 stdio 运行服务。

导入时只完成工具注册；配置读取和数据库连接在实际工具调用时进行。
"""

from fastmcp import FastMCP
from thoth.tools import register_tools

# 严格检查对象、数组及字段类型，在进入业务层前拒绝结构错误。
mcp = FastMCP(name="thoth-words", strict_input_validation=True)
register_tools(mcp)


if __name__ == "__main__":
    # stdio 的标准输出用于协议通信，关闭启动横幅以免混入工具消息。
    mcp.run(transport="stdio", show_banner=False, log_level="ERROR")
