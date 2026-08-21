"""add completed_at to tasks

Revision ID: 504be5ecbf1f
Revises: e76468fc7fa9
Create Date: 2026-08-21 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '504be5ecbf1f'
down_revision: Union[str, Sequence[str], None] = 'e76468fc7fa9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tasks', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tasks', 'completed_at')
