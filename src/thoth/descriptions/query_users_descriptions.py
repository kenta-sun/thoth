"""query_users 的独立对外说明，由工具入口注册。"""

QUERY_USERS_DESCRIPTION = """无参数，只读查询已有用户名，按用户 ID 升序返回。
返回 {"results":[{"username":"用户名"}]}，没有用户时 results 为空数组。
用户名由使用者手动通过 SQL 维护，不提供用户新增、修改、删除或登录功能。
其他工具的 username 必须使用已有用户名，不能猜测或自动创建。
"""
