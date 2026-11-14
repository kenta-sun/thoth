CREATE TABLE public.word_fam_tbl
(
    user_id    BIGINT      NOT NULL,
    word_id    BIGINT      NOT NULL,
    tag_code   VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(128) DEFAULT CURRENT_USER,
    updated_by VARCHAR(128) DEFAULT CURRENT_USER,

    CONSTRAINT pk_word_fam_tbl
        PRIMARY KEY (user_id, word_id),

    CONSTRAINT fk_word_fam_tbl_user_tbl
        FOREIGN KEY (user_id)
        REFERENCES public.user_tbl (id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_word_fam_tbl_word_tbl
        FOREIGN KEY (word_id)
        REFERENCES public.word_tbl (id)
        ON DELETE CASCADE,

    CONSTRAINT fk_word_fam_tbl_tag_tbl
        FOREIGN KEY (tag_code)
        REFERENCES public.tag_tbl (code)
        ON DELETE RESTRICT
);

COMMENT ON TABLE public.word_fam_tbl
    IS '用户单词熟悉度表';

COMMENT ON COLUMN public.word_fam_tbl.user_id
    IS '用户ID';
COMMENT ON COLUMN public.word_fam_tbl.word_id
    IS '单词ID';
COMMENT ON COLUMN public.word_fam_tbl.tag_code
    IS '当前熟悉度标签编码';
COMMENT ON COLUMN public.word_fam_tbl.created_at
    IS '创建时间';
COMMENT ON COLUMN public.word_fam_tbl.updated_at
    IS '最后更新时间';
COMMENT ON COLUMN public.word_fam_tbl.created_by
    IS '创建者';
COMMENT ON COLUMN public.word_fam_tbl.updated_by
    IS '最后修改者';