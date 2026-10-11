"""MCP 启动模块：加载统一注册的工具，并以 stdio 运行服务。

导入时只完成工具注册；配置读取和数据库连接在实际工具调用时进行。
"""

from thoth.tools.mcp_tools import mcp


if __name__ == "__main__":
    # stdio 的标准输出用于协议通信，关闭启动横幅以免混入工具消息。
    mcp.run(transport="stdio", show_banner=False, log_level="ERROR")
