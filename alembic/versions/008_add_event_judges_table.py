"""add event_judges table

Revision ID: 008
Revises: 007
Create Date: 2026-02-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    # Проверяем существование таблицы перед созданием
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'event_judges')"
    ))
    table_exists = result.scalar()
    
    if not table_exists:
        op.create_table(
            'event_judges',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('event_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('judge_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['judge_id'], ['users.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('event_id', 'judge_id', name='uq_event_judge')
        )
        op.create_index('ix_event_judges_event_id', 'event_judges', ['event_id'])
        op.create_index('ix_event_judges_judge_id', 'event_judges', ['judge_id'])


def downgrade():
    op.drop_index('ix_event_judges_judge_id', table_name='event_judges')
    op.drop_index('ix_event_judges_event_id', table_name='event_judges')
    op.drop_table('event_judges')
