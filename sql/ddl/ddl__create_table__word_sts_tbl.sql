-- ============================================================
-- 单词状态表
-- ============================================================

CREATE TABLE word_sts_tbl
(
    code           CHAR(1) PRIMARY KEY,
    description    TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     VARCHAR(128) DEFAULT CURRENT_USER,
    updated_by     VARCHAR(128) DEFAULT CURRENT_USER,
    CONSTRAINT ck_word_sts_tbl_code CHECK (code ~ '^[A-Z]$')
);

COMMENT ON TABLE word_sts_tbl IS '单词状态表';

COMMENT ON COLUMN word_sts_tbl.code IS '状态编码，大写英文字母，作为主键';
COMMENT ON COLUMN word_sts_tbl.description IS '状态的中文说明';
COMMENT ON COLUMN word_sts_tbl.created_at IS '创建时间';
COMMENT ON COLUMN word_sts_tbl.updated_at IS '最后更新时间';
COMMENT ON COLUMN word_sts_tbl.created_by IS '创建者';
COMMENT ON COLUMN word_sts_tbl.updated_by IS '最后修改者';
