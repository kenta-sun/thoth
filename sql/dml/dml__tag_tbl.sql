-- 自动生成：来源 thoth.common.tags.TAG_DEFINITIONS，请勿手工修改。
-- 前置表：tag_tbl；仅插入缺失编码，保留已有记录。

INSERT INTO tag_tbl (code, zh_name, jp_name)
VALUES
    (E'v', E'动词', E'動詞'),
    (E'v1', E'Ⅰ类动词', E'Ⅰ類動詞'),
    (E'v2', E'Ⅱ类动词', E'Ⅱ類動詞'),
    (E'v3', E'Ⅲ类动词', E'Ⅲ類動詞'),
    (E'adj', E'形容词', E'形容詞'),
    (E'adj_i', E'イ形容词', E'イ形容詞'),
    (E'adj_na', E'ナ形容词', E'ナ形容詞'),
    (E'n', E'名词', E'名詞'),
    (E'adv', E'副词', E'副詞'),
    (E'num', E'数量词', E'数量詞')
ON CONFLICT (code) DO NOTHING;
