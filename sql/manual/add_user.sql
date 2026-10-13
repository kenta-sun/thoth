-- 手动添加用户示例：将“请替换为你的用户名”替换后执行。
-- 不会更新同名用户；本文件不会随重建脚本自动执行。
INSERT INTO user_tbl (username)
VALUES ('请替换为你的用户名')
ON CONFLICT (username) DO NOTHING;
