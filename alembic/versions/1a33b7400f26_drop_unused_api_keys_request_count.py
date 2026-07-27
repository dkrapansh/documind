"""drop unused api_keys.request_count

Revision ID: 1a33b7400f26
Revises: fece9e31cbb3
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a33b7400f26'
down_revision: Union[str, None] = 'fece9e31cbb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Never read or written anywhere in app code - request counting is
    # handled entirely by middleware/rate_limit.py's in-memory limiter,
    # not persisted per key. Dead column since the initial migration.
    op.drop_column('api_keys', 'request_count')


def downgrade() -> None:
    op.add_column(
        'api_keys',
        sa.Column('request_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('api_keys', 'request_count', server_default=None)
