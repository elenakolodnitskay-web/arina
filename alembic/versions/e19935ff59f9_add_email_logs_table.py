"""add email_logs table

Revision ID: e19935ff59f9
Revises: 74d805f803d0
Create Date: 2026-08-20 16:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import db.crypto

# revision identifiers, used by Alembic.
revision: str = 'e19935ff59f9'
down_revision: Union[str, Sequence[str], None] = '74d805f803d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('email_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('recipient_email', db.crypto.EncryptedString(), nullable=False),
    sa.Column('subject', db.crypto.EncryptedString(), nullable=False),
    sa.Column('body', db.crypto.EncryptedString(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_email_logs_user_id'), 'email_logs', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_email_logs_user_id'), table_name='email_logs')
    op.drop_table('email_logs')
