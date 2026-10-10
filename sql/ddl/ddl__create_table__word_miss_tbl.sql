-- ============================================================
-- 陌生单词记录表
-- 前置表：word_tbl
-- ============================================================

CREATE TABLE word_miss_tbl
(
    word_id        BIGINT PRIMARY KEY,
    miss_count     BIGINT      NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     VARCHAR(128) DEFAULT CURRENT_USER,
    updated_by     VARCHAR(128) DEFAULT CURRENT_USER,
    CONSTRAINT ck_word_miss_tbl_miss_count CHECK (miss_count >= 0),
    CONSTRAINT fk_word_miss_tbl_word_tbl
        FOREIGN KEY (word_id)
            REFERENCES word_tbl (id)
            ON DELETE CASCADE
);

COMMENT ON TABLE word_miss_tbl IS '陌生单词记录表';

COMMENT ON COLUMN word_miss_tbl.word_id IS '单词ID，唯一主键';
COMMENT ON COLUMN word_miss_tbl.miss_count IS '陌生累计次数，包括默写错误和向AI询问单词';
COMMENT ON COLUMN word_miss_tbl.created_at IS '创建时间';
COMMENT ON COLUMN word_miss_tbl.updated_at IS '最后更新时间';
COMMENT ON COLUMN word_miss_tbl.created_by IS '创建者';
COMMENT ON COLUMN word_miss_tbl.updated_by IS '最后修改者';
