"""add stage_id to evaluations

Revision ID: 006
Revises: 005
Create Date: 2026-02-26 08:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем колонку stage_id в таблицу team_evaluations
    op.add_column('team_evaluations', sa.Column('stage_id', postgresql.UUID(as_uuid=True), nullable=True))
    
    # Создаем внешний ключ
    op.create_foreign_key(
        'fk_team_evaluations_stage_id',
        'team_evaluations',
        'stages',
        ['stage_id'],
        ['id'],
        ondelete='SET NULL'
    )
    
    # Создаем индекс для улучшения производительности запросов
    op.create_index('ix_team_evaluations_stage_id', 'team_evaluations', ['stage_id'])


def downgrade() -> None:
    # Удаляем индекс
    op.drop_index('ix_team_evaluations_stage_id', table_name='team_evaluations')
    
    # Удаляем внешний ключ
    op.drop_constraint('fk_team_evaluations_stage_id', 'team_evaluations', type_='foreignkey')
    
    # Удаляем колонку
    op.drop_column('team_evaluations', 'stage_id')
