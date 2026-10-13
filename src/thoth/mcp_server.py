"""MCP 启动模块：加载统一注册的工具，并以 Streamable HTTP 运行服务。

导入时只完成工具注册；启动时校验配置，数据库连接在实际工具调用时进行。
"""

from fastmcp import FastMCP
from thoth.tools import register_tools
from thoth.common.config import get_settings

# 严格检查对象、数组及字段类型，在进入业务层前拒绝结构错误。
mcp = FastMCP(name="thoth-words", strict_input_validation=True)
register_tools(mcp)


def main() -> None:
    """启动 /mcp HTTP 端点；监听地址与端口由 FASTMCP_HOST、FASTMCP_PORT 控制。

    本地默认监听 127.0.0.1:8000，Docker 在容器内监听 0.0.0.0。
    启用 Host/Origin 检查，只接受本机客户端；数据库在工具实际调用时连接。
    """
    # 在开放 HTTP 端口前发现缺失配置；此处不连接数据库。
    get_settings()
    mcp.run(
        transport="http", path="/mcp", show_banner=False, log_level="INFO",
        host_origin_protection=True,
        allowed_hosts=["localhost", "127.0.0.1"],
        allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
    )


if __name__ == "__main__":
    main()
