"""add is_auto_activate and auto_activate_at to stages

Revision ID: 004
Revises: 003
Create Date: 2025-01-XX

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поля для автоматической активации этапов
    op.add_column('stages', sa.Column('is_auto_activate', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('stages', sa.Column('auto_activate_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Удаляем поля автоматической активации
    op.drop_column('stages', 'auto_activate_at')
    op.drop_column('stages', 'is_auto_activate')
