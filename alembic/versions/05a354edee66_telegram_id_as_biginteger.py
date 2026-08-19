"""telegram_id as BigInteger

Revision ID: 05a354edee66
Revises: 58a5975bc3ea
Create Date: 2026-08-19 19:44:57.212695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '05a354edee66'
down_revision: Union[str, Sequence[str], None] = '58a5975bc3ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed dropping 'apscheduler_jobs' — that table is
    # created at runtime by APScheduler's SQLAlchemyJobStore, is not part of our
    # declarative models, and must not be touched by Alembic. Removed from this
    # migration; only the telegram_id type fix is applied.
    op.alter_column('users', 'telegram_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('users', 'telegram_id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False)
