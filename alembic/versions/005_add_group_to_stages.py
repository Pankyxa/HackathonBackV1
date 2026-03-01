"""add group to stages

Revision ID: 005
Revises: 004
Create Date: 2026-02-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле group для группировки этапов
    op.add_column('stages', sa.Column('group', sa.String(), nullable=True))


def downgrade() -> None:
    # Удаляем поле group
    op.drop_column('stages', 'group')
