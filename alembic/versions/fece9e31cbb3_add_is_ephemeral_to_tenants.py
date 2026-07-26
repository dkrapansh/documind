"""add is_ephemeral to tenants

Revision ID: fece9e31cbb3
Revises: 0f71963c69be
Create Date: 2026-07-26 16:24:44.619494

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fece9e31cbb3'
down_revision: Union[str, None] = '0f71963c69be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate also wanted to drop ix_chunks_embedding_hnsw - that
    # index was created via raw SQL in 0f71963c69be, not through
    # SQLAlchemy model metadata, so autogenerate can't see it and assumes
    # it shouldn't exist. Not touching it here; only the new column.
    op.add_column(
        'tenants',
        sa.Column('is_ephemeral', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('tenants', 'is_ephemeral', server_default=None)


def downgrade() -> None:
    op.drop_column('tenants', 'is_ephemeral')
