"""add membership plans and memberships tables

Revision ID: 4e20cbb57d32
Revises: 369b000bece1
Create Date: 2026-08-26 15:37:18.658560

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e20cbb57d32'
down_revision: Union[str, Sequence[str], None] = '369b000bece1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed dropping 'transactions' and 'email_queue' —
    # those tables have no SQLAlchemy model yet (pre-existing, unrelated to this change),
    # so those drops were removed from this migration.
    op.create_table('membership_plans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('duration_days', sa.Integer(), nullable=True),
    sa.Column('max_documents', sa.Integer(), nullable=True),
    sa.Column('max_queries_per_day', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('memberships',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('plan_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'EXPIRED', 'CANCELLED', name='membershipstatus'), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['plan_id'], ['membership_plans.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['shop_owners.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('memberships')
    op.drop_table('membership_plans')
