"""add events table and event_id to teams, stages, evaluations

Revision ID: 002
Revises: 001
Create Date: 2024-12-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
import uuid


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем таблицу events
    op.create_table(
        'events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1024), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )

    # Добавляем event_id к teams
    op.add_column('teams', sa.Column('event_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_teams_event_id', 'teams', 'events', ['event_id'], ['id'])

    # Добавляем event_id к stages
    op.add_column('stages', sa.Column('event_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_stages_event_id', 'stages', 'events', ['event_id'], ['id'])
    
    # Убираем unique constraint с order в stages, так как теперь order уникален только в рамках события
    op.drop_constraint('stages_order_key', 'stages', type_='unique')
    op.create_unique_constraint('uq_stages_event_order', 'stages', ['event_id', 'order'])

    # Добавляем event_id к team_evaluations
    op.add_column('team_evaluations', sa.Column('event_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_team_evaluations_event_id', 'team_evaluations', 'events', ['event_id'], ['id'])

    # Создаем дефолтное событие для существующих данных
    default_event_id = uuid.uuid4()
    op.execute(
        sa.text(f"""
            INSERT INTO events (id, name, description, is_active, created_at)
            VALUES ('{default_event_id}', 'Хакатон 2024', 'Дефолтное событие для существующих данных', true, NOW())
        """)
    )

    # Устанавливаем event_id для всех существующих записей
    op.execute(
        sa.text(f"""
            UPDATE teams SET event_id = '{default_event_id}' WHERE event_id IS NULL
        """)
    )
    op.execute(
        sa.text(f"""
            UPDATE stages SET event_id = '{default_event_id}' WHERE event_id IS NULL
        """)
    )
    op.execute(
        sa.text(f"""
            UPDATE team_evaluations SET event_id = '{default_event_id}' WHERE event_id IS NULL
        """)
    )

    # Делаем event_id обязательным полем
    op.alter_column('teams', 'event_id', nullable=False)
    op.alter_column('stages', 'event_id', nullable=False)
    op.alter_column('team_evaluations', 'event_id', nullable=False)


def downgrade() -> None:
    # Убираем обязательность event_id
    op.alter_column('team_evaluations', 'event_id', nullable=True)
    op.alter_column('stages', 'event_id', nullable=True)
    op.alter_column('teams', 'event_id', nullable=True)

    # Удаляем связи
    op.drop_constraint('fk_team_evaluations_event_id', 'team_evaluations', type_='foreignkey')
    op.drop_constraint('fk_stages_event_id', 'stages', type_='foreignkey')
    op.drop_constraint('fk_teams_event_id', 'teams', type_='foreignkey')

    # Восстанавливаем unique constraint для order в stages
    op.drop_constraint('uq_stages_event_order', 'stages', type_='unique')
    op.create_unique_constraint('stages_order_key', 'stages', ['order'])

    # Удаляем колонки event_id
    op.drop_column('team_evaluations', 'event_id')
    op.drop_column('stages', 'event_id')
    op.drop_column('teams', 'event_id')

    # Удаляем таблицу events
    op.drop_table('events')
