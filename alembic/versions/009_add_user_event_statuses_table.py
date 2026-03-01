"""add user_event_statuses table

Revision ID: 009
Revises: 008
Create Date: 2026-03-01 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    # Проверяем существование таблицы перед созданием
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'user_event_statuses')"
    ))
    table_exists = result.scalar()
    
    if not table_exists:
        op.create_table(
            'user_event_statuses',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('event_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('status_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['status_id'], ['user_status_types.id']),
            sa.UniqueConstraint('user_id', 'event_id', name='uq_user_event_status')
        )
        op.create_index('ix_user_event_statuses_user_id', 'user_event_statuses', ['user_id'])
        op.create_index('ix_user_event_statuses_event_id', 'user_event_statuses', ['event_id'])
        op.create_index('ix_user_event_statuses_status_id', 'user_event_statuses', ['status_id'])


def downgrade():
    op.drop_index('ix_user_event_statuses_status_id', table_name='user_event_statuses')
    op.drop_index('ix_user_event_statuses_event_id', table_name='user_event_statuses')
    op.drop_index('ix_user_event_statuses_user_id', table_name='user_event_statuses')
    op.drop_table('user_event_statuses')
