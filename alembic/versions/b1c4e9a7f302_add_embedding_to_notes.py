"""add embedding to notes

Revision ID: b1c4e9a7f302
Revises: 73a53689f2c7
Create Date: 2026-08-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'b1c4e9a7f302'
down_revision: Union[str, Sequence[str], None] = '73a53689f2c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.add_column(
        'notes',
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=True),
    )
    # HNSW — не требует предварительного обучения на данных (в отличие от
    # IVFFlat), подходит для таблицы, которая с нуля пустая и растёт постепенно.
    op.execute(
        'CREATE INDEX ix_notes_embedding_cosine ON notes '
        'USING hnsw (embedding vector_cosine_ops)'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('DROP INDEX IF EXISTS ix_notes_embedding_cosine')
    op.drop_column('notes', 'embedding')
