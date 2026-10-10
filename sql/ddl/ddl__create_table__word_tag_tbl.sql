-- ============================================================
-- 单词标签关联表
-- 前置表：word_tbl、tag_tbl
-- ============================================================

CREATE TABLE word_tag_tbl
(
    word_id        BIGINT      NOT NULL,
    tag_code       VARCHAR(32) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     VARCHAR(128) DEFAULT CURRENT_USER,
    updated_by     VARCHAR(128) DEFAULT CURRENT_USER,
    CONSTRAINT pk_word_tag_tbl PRIMARY KEY (word_id, tag_code),
    CONSTRAINT fk_word_tag_tbl_word_tbl
        FOREIGN KEY (word_id)
            REFERENCES word_tbl (id)
            ON DELETE CASCADE,
    CONSTRAINT fk_word_tag_tbl_tag_tbl
        FOREIGN KEY (tag_code)
            REFERENCES tag_tbl (code)
            ON DELETE RESTRICT
);

COMMENT ON TABLE word_tag_tbl IS '单词标签关联表';

COMMENT ON COLUMN word_tag_tbl.word_id IS '单词ID，与标签编码构成联合主键';
COMMENT ON COLUMN word_tag_tbl.tag_code IS '标签编码，与单词ID构成联合主键';
COMMENT ON COLUMN word_tag_tbl.created_at IS '创建时间';
COMMENT ON COLUMN word_tag_tbl.updated_at IS '最后更新时间';
COMMENT ON COLUMN word_tag_tbl.created_by IS '创建者';
COMMENT ON COLUMN word_tag_tbl.updated_by IS '最后修改者';
