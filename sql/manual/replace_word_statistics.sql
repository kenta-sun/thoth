-- 一次性替换旧统计表：丢弃 miss、usage 旧计数，不迁移数据。
-- 保留用户、单词、标签及其他业务表；新统计表初始为空。
-- 停止旧版 MCP，确认目标库后整份执行；客户端报错须停止并 ROLLBACK。
-- 在单事务内创建新表和字典、删除旧表；外部依赖存在时失败回滚，不使用 CASCADE。
-- 不可重复执行；新表已存在时 CREATE TABLE 失败，避免清空已有新统计。
-- 由 python -m thoth.utils.generate_rebuild_sql 生成，勿单独维护合并内容。
BEGIN;

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

-- 计数类型预置数据；前置表：count_type_tbl。重复初始化保留已有记录。
INSERT INTO count_type_tbl (code, description)
VALUES
    ('miss', '没记起单词的次数'),
    ('usage', '见到单词的次数'),
    ('inf_miss', '不认识活用形式、不会变形或变形答错的次数，归到对应词典形')
ON CONFLICT (code) DO NOTHING;

DROP TABLE word_miss_tbl;
DROP TABLE word_usage_tbl;
COMMIT;
