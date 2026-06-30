"""${message}

修订 ID: ${up_revision}
创建时间: ${create_date}

迁移类型:
  - 升级 (upgrade): ${up_revision} → ${down_revision or "新"}
  - 降级 (downgrade): ${down_revision or "新"} → ${up_revision}
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# 修订标识
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """升级数据库结构。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """降级数据库结构（回滚）。"""
    ${downgrades if downgrades else "pass"}
