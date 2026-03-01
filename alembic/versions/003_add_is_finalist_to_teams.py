"""add is_finalist to teams

Revision ID: 003
Revises: 002
Create Date: 2025-01-XX

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле is_finalist в таблицу teams
    op.add_column('teams', sa.Column('is_finalist', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    # Удаляем поле is_finalist из таблицы teams
    op.drop_column('teams', 'is_finalist')
