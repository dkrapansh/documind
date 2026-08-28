"""add ingestion job state, document_contents, and chunk uniqueness

Revision ID: a1c4e7b92f30
Revises: 1a33b7400f26
Create Date: 2026-08-28 10:00:00.000000

Makes ingestion durable and idempotent. Before this, an ingestion job existed
only as a closure inside FastAPI's BackgroundTasks, so a restart mid-job left
the document at "processing" forever with nothing recording that the work had
started. See docs/FAILURE_MODE_ANALYSIS.md failure modes 8, 10, 26, 40.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4e7b92f30'
down_revision: Union[str, None] = '1a33b7400f26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ingestion job bookkeeping. server_default on attempt_count so existing
    # rows get 0 rather than NULL, then dropped so the application (not the
    # database) owns the default from here on.
    op.add_column(
        'documents',
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('documents', 'attempt_count', server_default=None)
    op.add_column(
        'documents', sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'documents', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('documents', sa.Column('error_reason', sa.String(length=500), nullable=True))

    # Partial index over just the claimable rows. The worker's claim query
    # filters on status = 'pending', which is a small slice of the table in
    # steady state, so indexing only those rows keeps the index tiny and
    # avoids touching it on every ready/failed document.
    op.create_index(
        'ix_documents_pending_claim',
        'documents',
        ['id'],
        postgresql_where=sa.text("status = 'pending'"),
    )
    # Recovery scans for expired leases among processing rows only.
    op.create_index(
        'ix_documents_stale_lease',
        'documents',
        ['lease_expires_at'],
        postgresql_where=sa.text("status = 'processing'"),
    )

    op.create_table(
        'document_contents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_document_contents_document_id'),
        'document_contents',
        ['document_id'],
        unique=True,
    )

    # Deduplicate before adding the constraint. No production run has been
    # able to create duplicates (the only caller was the upload path, which
    # dedupes by content hash and never re-ran a job), but a table that
    # somehow holds them would fail this migration at the worst possible
    # moment, during a deploy. Keeps the lowest id per (document_id,
    # chunk_index), which is the row the original ingestion wrote.
    op.execute(
        """
        DELETE FROM chunks a
        USING chunks b
        WHERE a.document_id = b.document_id
          AND a.chunk_index = b.chunk_index
          AND a.id > b.id
        """
    )
    op.create_unique_constraint(
        'uq_chunks_document_id_chunk_index', 'chunks', ['document_id', 'chunk_index']
    )


def downgrade() -> None:
    op.drop_constraint('uq_chunks_document_id_chunk_index', 'chunks', type_='unique')
    op.drop_index(op.f('ix_document_contents_document_id'), table_name='document_contents')
    op.drop_table('document_contents')
    op.drop_index('ix_documents_stale_lease', table_name='documents')
    op.drop_index('ix_documents_pending_claim', table_name='documents')
    op.drop_column('documents', 'error_reason')
    op.drop_column('documents', 'lease_expires_at')
    op.drop_column('documents', 'processing_started_at')
    op.drop_column('documents', 'attempt_count')
