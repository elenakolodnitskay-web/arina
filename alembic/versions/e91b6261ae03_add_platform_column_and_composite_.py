"""add platform column and composite unique constraint

Revision ID: e91b6261ae03
Revises: 05a354edee66
Create Date: 2026-08-20 13:57:22.982734

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e91b6261ae03'
down_revision: Union[str, Sequence[str], None] = '05a354edee66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate again proposed dropping 'apscheduler_jobs' — that table is
    # created at runtime by APScheduler's SQLAlchemyJobStore, is not part of our
    # declarative models, and must not be touched by Alembic. Removed from this
    # migration, as in 05a354edee66.
    op.add_column('users', sa.Column('platform', sa.String(length=16), server_default='telegram', nullable=False))
    op.drop_index(op.f('ix_users_telegram_id'), table_name='users')
    op.create_index(op.f('ix_users_telegram_id'), 'users', ['telegram_id'], unique=False)
    op.create_unique_constraint('uq_users_platform_telegram_id', 'users', ['platform', 'telegram_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_users_platform_telegram_id', 'users', type_='unique')
    op.drop_index(op.f('ix_users_telegram_id'), table_name='users')
    op.create_index(op.f('ix_users_telegram_id'), 'users', ['telegram_id'], unique=True)
    op.drop_column('users', 'platform')
