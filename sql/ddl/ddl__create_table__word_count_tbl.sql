-- ============================================================
-- 单词分类计数表
-- 前置表：word_tbl、user_tbl、count_type_tbl
-- ============================================================

CREATE TABLE word_count_tbl
(
    user_id        BIGINT      NOT NULL,
    word_id        BIGINT      NOT NULL,
    count_type     TEXT        NOT NULL,
    count_value    BIGINT      NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by     VARCHAR(128) DEFAULT CURRENT_USER,
    updated_by     VARCHAR(128) DEFAULT CURRENT_USER,
    CONSTRAINT pk_word_count_tbl PRIMARY KEY (user_id, word_id, count_type),
    CONSTRAINT fk_word_count_tbl_user_tbl FOREIGN KEY (user_id)
        REFERENCES user_tbl (id) ON DELETE RESTRICT,
    CONSTRAINT fk_word_count_tbl_count_type_tbl FOREIGN KEY (count_type)
        REFERENCES count_type_tbl (code) ON DELETE RESTRICT,
    CONSTRAINT ck_word_count_tbl_count_value CHECK (count_value >= 0),
    CONSTRAINT fk_word_count_tbl_word_tbl
        FOREIGN KEY (word_id)
            REFERENCES word_tbl (id)
            ON DELETE CASCADE
);

COMMENT ON TABLE word_count_tbl IS '单词分类计数表';

COMMENT ON COLUMN word_count_tbl.user_id IS '用户ID';
COMMENT ON COLUMN word_count_tbl.word_id IS '单词ID';
COMMENT ON COLUMN word_count_tbl.count_type IS '计数类型';
COMMENT ON COLUMN word_count_tbl.count_value IS '该用户对该单词在指定类型下的累计次数，非负，默认0';
COMMENT ON COLUMN word_count_tbl.created_at IS '创建时间';
COMMENT ON COLUMN word_count_tbl.updated_at IS '最后更新时间';
COMMENT ON COLUMN word_count_tbl.created_by IS '创建者';
COMMENT ON COLUMN word_count_tbl.updated_by IS '最后修改者';
