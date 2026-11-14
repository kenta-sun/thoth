-- 计数类型预置数据；前置表：count_type_tbl。重复初始化保留已有记录。
INSERT INTO count_type_tbl (code, description)
VALUES
    ('miss', '没记起单词的次数'),
    ('usage', '见到单词的次数'),
    ('inf_miss', '不认识活用形式、不会变形或变形答错的次数，归到对应词典形')
ON CONFLICT (code) DO NOTHING;
