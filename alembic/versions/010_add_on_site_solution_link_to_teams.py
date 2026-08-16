"""add on_site_solution_link to teams

Revision ID: 010
Revises: 009
Create Date: 2026-08-16 15:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'teams',
        sa.Column('on_site_solution_link', sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('teams', 'on_site_solution_link')
