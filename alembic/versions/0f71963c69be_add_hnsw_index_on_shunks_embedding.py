"""add hnsw index on chunks embedding

Revision ID: 0f71963c69be
Revises: ccdd963f96f2
Create Date: 2026-07-15 13:54:29.264140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0f71963c69be'
down_revision: Union[str, None] = 'ccdd963f96f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    


def downgrade() -> None:
    op.execute("DROP INDEX ix_chunks_embedding_hnsw")