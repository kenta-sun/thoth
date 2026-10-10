"""数据模型层：为 JSON 输入、业务处理和数据库读写提供统一的表记录对象。

六类实体的字段名称和基础类型与各表对应。当前单词流程从 JSON 构造 WordEntity，
经业务层传给仓储，查询和保存返回的数据库行也映射为 WordEntity。
所有字段均默认 None，允许空构造、部分构造和后续赋值；实体仅承载数据，
不执行类型、非空或业务校验。字段注释中的必填、取值范围和默认值描述业务或表约束，
由业务层及数据库负责，实体本身不会应用数据库默认值。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class WordEntity:
    """word_tbl 的单词记录，承载输入信息及数据库返回的标识、状态和审计字段。"""

    id: int | None = None  # 单词主键；未显式指定时由数据库 identity 生成。
    word: str | None = None  # 单词基本形式；表内唯一，按原文判重和定位，包含已删除记录。
    common_form: str | None = None  # 单词常用写法；新增业务要求调用方显式提供。
    hiragana: str | None = None  # 单词的平假名读音。
    meaning: str | None = None  # 单词的中文释义。
    status_code: str | None = None  # 关联 word_sts_tbl.code；A=正在使用，D=被删除，表默认 A。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新由 SQL 维护。
    created_by: str | None = None  # 创建者标识；表默认当前数据库角色，单词仓储写入配置的操作者。
    updated_by: str | None = None  # 最后修改者标识；表默认当前数据库角色，单词仓储写入当前操作者。


@dataclass(slots=True, kw_only=True)
class TagEntity:
    """tag_tbl 的标签字典记录，保存标签编码及其中日文名称。"""

    code: str | None = None  # 人工指定的标签主键；表约束仅接受英文字母、数字和下划线。
    zh_name: str | None = None  # 标签的中文名称。
    jp_name: str | None = None  # 标签的日文名称。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。


@dataclass(slots=True, kw_only=True)
class WordStatusEntity:
    """word_sts_tbl 的状态字典记录，供单词表通过状态编码关联。"""

    code: str | None = None  # 人工指定的状态主键，表约束为单个大写字母；A=正在使用，D=被删除。
    description: str | None = None  # 状态的中文说明。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。


@dataclass(slots=True, kw_only=True)
class WordTagEntity:
    """word_tag_tbl 的单词标签关联记录，一条记录表示一个单词具有一个标签。"""

    word_id: int | None = None  # 关联 word_tbl.id，与 tag_code 组成联合主键。
    tag_code: str | None = None  # 关联 tag_tbl.code，与 word_id 组成联合主键。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。


@dataclass(slots=True, kw_only=True)
class WordUsageEntity:
    """word_usage_tbl 的使用统计记录，按单词汇总出题或写文章时的累计使用次数。"""

    word_id: int | None = None  # 关联 word_tbl.id 的主键，每个单词最多一条使用统计。
    usage_count: int | None = None  # 出题或写文章时使用该词的累计次数；表默认 0，并限制非负。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。


@dataclass(slots=True, kw_only=True)
class WordMissEntity:
    """word_miss_tbl 的陌生词统计记录，按单词汇总默写错误和向 AI 询问的次数。"""

    word_id: int | None = None  # 关联 word_tbl.id 的主键，每个单词最多一条陌生统计。
    miss_count: int | None = None  # 默写错误及向 AI 询问该词的累计次数；表默认 0，并限制非负。
    created_at: datetime | None = None  # 带时区的创建时间；表默认值为数据库当前时间。
    updated_at: datetime | None = None  # 带时区的最后更新时间；插入默认当前时间，更新需由 SQL 维护。
    created_by: str | None = None  # 创建者标识；未指定时表默认当前数据库角色。
    updated_by: str | None = None  # 最后修改者标识；未指定时表默认当前数据库角色。
