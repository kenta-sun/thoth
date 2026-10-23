"""查询 DTO 层：承载解析条件、SQL 构建配置和关联查询结果，不替代表实体。"""

from dataclasses import dataclass, field
from collections.abc import Mapping

from thoth.entity import WordEntity, WordUsageEntity, WordMissEntity, WordTagEntity


@dataclass(frozen=True, slots=True)
class QueryCondition:
    """承载一个已校验的字段条件；同一请求的条件全部同时满足。"""

    field: str  # 对外业务字段名，不是任意 SQL 表达式。
    operator: str  # eq、in、like 或数值比较操作。
    value: str | int | tuple[str | int, ...]  # in 保存非空元组，其余操作保存单值。


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """承载查询请求；由 Service 解析后传入 Mapper 和构建器。"""

    fields: tuple[str, ...]  # 需要返回的业务字段，顺序与请求一致。
    conditions: tuple[QueryCondition, ...] = ()  # 空元组表示没有额外筛选。
    sort: tuple[tuple[str, str | None], ...] = ()  # 按优先级排列的字段和方向；仅 random 可用 None，空元组不排序。
    limit: int | None = None  # None 表示不限数量；其余值必须为正整数。


@dataclass(frozen=True, slots=True)
class SqlField:
    """承载由 Mapper 提供的可信字段表达式及其关联依赖。"""

    expression: str  # 后端固定的 SQL 表达式，不能来自用户输入。
    operators: frozenset[str]  # 此字段允许的筛选操作。
    sortable: bool = True  # False 表示不允许参与排序。
    joins: tuple[str, ...] = ()  # 需要的关联配置名称。
    membership_expression: str | None = None  # 集合关联筛选模板，{value} 仅替换为绑定占位符。


@dataclass(frozen=True, slots=True)
class QuerySqlSpec:
    """由 Mapper 定义查询范围，供纯 SQL 构建器使用。"""

    source: str  # 固定主表及别名。
    predicate: str  # 不允许请求覆盖的固定筛选条件。
    fields: Mapping[str, SqlField]  # 允许查询的业务字段白名单。
    joins: Mapping[str, str]  # 固定关联 SQL，按配置顺序输出。


@dataclass(frozen=True, slots=True)
class BuiltQuery:
    """保存可执行的 SQL 模板和独立绑定参数，不包含数据库连接。"""

    sql: str  # 含驱动命名占位符的 SQL 模板。
    params: dict[str, object]  # 条件值及 limit，交由驱动绑定而非字符串插值。


@dataclass(slots=True)
class QueryWordResult:
    """通过各表实体承载查询结果；未投影的字段保持 None 或空列表。"""

    word: WordEntity = field(default_factory=WordEntity)  # 单词主表投影。
    usage: WordUsageEntity = field(default_factory=WordUsageEntity)  # 使用次数，查询缺失行视为零。
    miss: WordMissEntity = field(default_factory=WordMissEntity)  # 陌生次数，查询缺失行视为零。
    tags: list[WordTagEntity] = field(default_factory=list)  # 按编码排序的标签关联投影。
