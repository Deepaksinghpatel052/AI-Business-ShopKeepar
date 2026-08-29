"""add demo mode fields to shop_owners

Revision ID: 369b000bece1
Revises: 2a383a8b5b1a
Create Date: 2026-08-22 01:04:37.590189

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '369b000bece1'
down_revision: Union[str, Sequence[str], None] = '2a383a8b5b1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed dropping 'transactions' and 'email_queue' —
    # those tables have no SQLAlchemy model yet (pre-existing, unrelated to this change),
    # so those drops were removed from this migration.
    op.add_column('shop_owners', sa.Column('demo_mode_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('shop_owners', sa.Column('demo_dataset', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('shop_owners', 'demo_dataset')
    op.drop_column('shop_owners', 'demo_mode_enabled')
