"""add tariff to users

Revision ID: c7e2a815f9b1
Revises: b1c4e9a7f302
Create Date: 2026-08-21 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7e2a815f9b1'
down_revision: Union[str, Sequence[str], None] = 'b1c4e9a7f302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column(
            'tariff',
            sa.Enum('secretary', 'accountant', 'trusted', name='tariff', native_enum=False, length=16),
            server_default='trusted',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'tariff')
