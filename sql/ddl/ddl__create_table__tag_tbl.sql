-- ============================================================
-- 标签表
-- ============================================================

CREATE TABLE tag_tbl
(
    code           VARCHAR(32) PRIMARY KEY,
    zh_name        TEXT        NOT NULL,
    jp_name        TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     VARCHAR(128) DEFAULT CURRENT_USER,
    updated_by     VARCHAR(128) DEFAULT CURRENT_USER,
    CONSTRAINT ck_tag_tbl_code CHECK (code ~ '^[A-Za-z0-9_]+$')
);

COMMENT ON TABLE tag_tbl IS '标签表';

COMMENT ON COLUMN tag_tbl.code IS '标签编码，人工指定的主键，仅允许英文字母、数字和下划线';
COMMENT ON COLUMN tag_tbl.zh_name IS '标签中文名称';
COMMENT ON COLUMN tag_tbl.jp_name IS '标签日文名称';
COMMENT ON COLUMN tag_tbl.created_at IS '创建时间';
COMMENT ON COLUMN tag_tbl.updated_at IS '最后更新时间';
COMMENT ON COLUMN tag_tbl.created_by IS '创建者';
COMMENT ON COLUMN tag_tbl.updated_by IS '最后修改者';
