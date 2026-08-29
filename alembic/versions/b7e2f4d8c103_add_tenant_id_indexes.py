"""add indexes on tenant-scoped columns

Revision ID: b7e2f4d8c103
Revises: a1c4e7b92f30
Create Date: 2026-08-29 19:30:00.000000

Every table carries tenant_id and every query filters on it inside the SQL,
which is the isolation guarantee this project is built around. None of those
columns was indexed, so each of those filters was a sequential scan.

It has not mattered so far because the tables are small. It is the kind of
thing that stops being invisible exactly when a demo starts getting traffic,
and the worst-affected query is the one on the hot path: BM25 loads every
chunk belonging to a tenant on every single question asked.

Plain CREATE INDEX rather than CONCURRENTLY: Alembic runs migrations inside a
transaction and CONCURRENTLY cannot, and at these table sizes the lock is
measured in milliseconds. On a large table this decision would need
revisiting, together with the start-up behavior, since a long index build
would block the release.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7e2f4d8c103'
down_revision: Union[str, None] = 'a1c4e7b92f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The hot one. services/bm25_retrieval.py selects every chunk for a
    # tenant on every query, and retrieval filters chunks by tenant_id inside
    # the SQL rather than after fetching.
    op.create_index('ix_chunks_tenant_id', 'chunks', ['tenant_id'])

    # GET /documents, and the ephemeral tenant sweep.
    op.create_index('ix_documents_tenant_id', 'documents', ['tenant_id'])
    # The upload dedupe lookup filters on both columns together. The existing
    # single-column index on content_hash cannot serve that as well, since
    # content_hash is the less selective half once a tenant is fixed.
    op.create_index(
        'ix_documents_tenant_id_content_hash', 'documents', ['tenant_id', 'content_hash']
    )

    # GET /history/{session_id} filters on both, and tenant_id is what keeps
    # one tenant from reading another's history with a guessed session id.
    op.create_index(
        'ix_query_logs_tenant_id_session_id', 'query_logs', ['tenant_id', 'session_id']
    )

    op.create_index('ix_eval_runs_tenant_id', 'eval_runs', ['tenant_id'])
    op.create_index('ix_api_keys_tenant_id', 'api_keys', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_api_keys_tenant_id', table_name='api_keys')
    op.drop_index('ix_eval_runs_tenant_id', table_name='eval_runs')
    op.drop_index('ix_query_logs_tenant_id_session_id', table_name='query_logs')
    op.drop_index('ix_documents_tenant_id_content_hash', table_name='documents')
    op.drop_index('ix_documents_tenant_id', table_name='documents')
    op.drop_index('ix_chunks_tenant_id', table_name='chunks')
