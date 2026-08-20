"""add transactions table and balance fields on users

Revision ID: 5cc8b2c5aee2
Revises: e91b6261ae03
Create Date: 2026-08-20 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import db.crypto

# revision identifiers, used by Alembic.
revision: str = '5cc8b2c5aee2'
down_revision: Union[str, Sequence[str], None] = 'e91b6261ae03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('balance', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('users', sa.Column('low_balance_threshold', sa.Numeric(precision=12, scale=2), nullable=True))
    op.create_table('transactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('transaction_type', sa.Enum('expense', 'income', name='transactiontype', native_enum=False, length=16), nullable=False),
    sa.Column('description', db.crypto.EncryptedString(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transactions_user_id'), 'transactions', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_transactions_user_id'), table_name='transactions')
    op.drop_table('transactions')
    op.drop_column('users', 'low_balance_threshold')
    op.drop_column('users', 'balance')
