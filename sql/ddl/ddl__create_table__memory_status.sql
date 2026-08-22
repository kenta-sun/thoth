-- ============================================================
-- 记忆状态字典表
-- ============================================================

CREATE TABLE memory_status
(
    code        CHAR(1) PRIMARY KEY,
    name        VARCHAR(32) NOT NULL,
    description VARCHAR(255),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by  VARCHAR(128),
    updated_by  VARCHAR(128)
);

COMMENT ON TABLE memory_status IS '记忆状态字典表';

COMMENT ON COLUMN memory_status.code IS '状态编码，同时作为主键';
COMMENT ON COLUMN memory_status.name IS '状态名称';
COMMENT ON COLUMN memory_status.description IS '状态说明';
COMMENT ON COLUMN memory_status.created_at IS '创建时间';
COMMENT ON COLUMN memory_status.updated_at IS '最后更新时间';
COMMENT ON COLUMN memory_status.created_by IS '创建者';
COMMENT ON COLUMN memory_status.updated_by IS '最后修改者';
