"""
Thoth —— 面向大语言模型的个人长期记忆服务。

包结构说明：
- ``config``      ：集中管理运行期配置（模型名、数据库连接、去重阈值等）。
- ``models``      ：记忆类型枚举与各处理阶段的数据模型。
- ``llm``         ：大语言模型与 Embedding 模型的统一封装、提示词常量。
- ``db``          ：PostgreSQL + pgvector 数据访问层。
- ``extraction``  ：记忆提取流水线（粗提取 → 分类 → 精炼 → 摘要 → 查重 → 写库）。
- ``mcp_server``  ：对外暴露的 MCP Server（当前仍为 demo 实现）。
- ``main``        ：本地命令行入口，便于不经过 MCP 直接调试提取流水线。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
