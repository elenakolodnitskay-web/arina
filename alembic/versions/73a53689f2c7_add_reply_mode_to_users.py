"""add reply_mode to users

Revision ID: 73a53689f2c7
Revises: 504be5ecbf1f
Create Date: 2026-08-21 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '73a53689f2c7'
down_revision: Union[str, Sequence[str], None] = '504be5ecbf1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column(
            'reply_mode',
            sa.Enum('text', 'voice', name='replymode', native_enum=False, length=8),
            server_default='text',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'reply_mode')
