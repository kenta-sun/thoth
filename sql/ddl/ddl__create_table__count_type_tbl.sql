-- ============================================================
-- 计数类型表
-- ============================================================

CREATE TABLE count_type_tbl
(
    code           TEXT PRIMARY KEY,
    description    TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     VARCHAR(128) DEFAULT CURRENT_USER,
    updated_by     VARCHAR(128) DEFAULT CURRENT_USER
);

COMMENT ON TABLE count_type_tbl IS '计数类型表';

COMMENT ON COLUMN count_type_tbl.code IS '计数类型';
COMMENT ON COLUMN count_type_tbl.description IS '计数类型的中文说明';
COMMENT ON COLUMN count_type_tbl.created_at IS '创建时间';
COMMENT ON COLUMN count_type_tbl.updated_at IS '最后更新时间';
COMMENT ON COLUMN count_type_tbl.created_by IS '创建者';
COMMENT ON COLUMN count_type_tbl.updated_by IS '最后修改者';
