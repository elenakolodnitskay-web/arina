"""drop dialog_summaries table

Revision ID: e76468fc7fa9
Revises: e19935ff59f9
Create Date: 2026-08-20 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import db.crypto

# revision identifiers, used by Alembic.
revision: str = 'e76468fc7fa9'
down_revision: Union[str, Sequence[str], None] = 'e19935ff59f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Фаза 19: LLM-пересуммаризация диалога заменена окном последних сообщений из
    # Note (core/dialog_summary.py) — пользователь явно попросил не терять детали
    # через сжатие. Таблица больше не используется, существующие summary отбрасываем
    # (это только кеш скользящего резюме, не источник истины — сама история осталась
    # в Note без изменений).
    op.drop_index(op.f('ix_dialog_summaries_user_id'), table_name='dialog_summaries')
    op.drop_table('dialog_summaries')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('dialog_summaries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('context', sa.Enum('work', 'personal', name='context', native_enum=False, length=16), nullable=False),
    sa.Column('summary_text', db.crypto.EncryptedString(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('message_count_since_update', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dialog_summaries_user_id'), 'dialog_summaries', ['user_id'], unique=False)
