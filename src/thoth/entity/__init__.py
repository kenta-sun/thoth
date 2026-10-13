"""表实体层：承载数据库记录，各字段允许为 None，不执行业务校验。"""

from thoth.entity.word import WordEntity
from thoth.entity.tag import TagEntity
from thoth.entity.word_status import WordStatusEntity
from thoth.entity.word_tag import WordTagEntity
from thoth.entity.word_usage import WordUsageEntity
from thoth.entity.word_miss import WordMissEntity

from thoth.entity.user import UserEntity

__all__ = ['WordEntity', 'TagEntity', 'WordStatusEntity', 'WordTagEntity', 'WordUsageEntity', 'WordMissEntity', 'UserEntity']
