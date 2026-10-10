-- ============================================================
-- 单词使用次数表
-- 前置表：word_tbl
-- ============================================================

CREATE TABLE word_usage_tbl
(
    word_id        BIGINT PRIMARY KEY,
    usage_count    BIGINT      NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     VARCHAR(128) DEFAULT CURRENT_USER,
    updated_by     VARCHAR(128) DEFAULT CURRENT_USER,
    CONSTRAINT ck_word_usage_tbl_usage_count CHECK (usage_count >= 0),
    CONSTRAINT fk_word_usage_tbl_word_tbl
        FOREIGN KEY (word_id)
            REFERENCES word_tbl (id)
            ON DELETE CASCADE
);

COMMENT ON TABLE word_usage_tbl IS '单词使用次数表';

COMMENT ON COLUMN word_usage_tbl.word_id IS '单词ID，唯一主键';
COMMENT ON COLUMN word_usage_tbl.usage_count IS '出题或写文章时使用单词的累计次数';
COMMENT ON COLUMN word_usage_tbl.created_at IS '创建时间';
COMMENT ON COLUMN word_usage_tbl.updated_at IS '最后更新时间';
COMMENT ON COLUMN word_usage_tbl.created_by IS '创建者';
COMMENT ON COLUMN word_usage_tbl.updated_by IS '最后修改者';
