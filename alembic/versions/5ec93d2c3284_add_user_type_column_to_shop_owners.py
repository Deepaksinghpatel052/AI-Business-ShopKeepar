"""add user_type column to shop_owners

Revision ID: 5ec93d2c3284
Revises: 4e20cbb57d32
Create Date: 2026-08-26 16:24:34.020794

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ec93d2c3284'
down_revision: Union[str, Sequence[str], None] = '4e20cbb57d32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed dropping 'transactions' and 'email_queue' —
    # those tables have no SQLAlchemy model yet (pre-existing, unrelated to this change),
    # so those drops were removed from this migration.
    op.add_column('shop_owners', sa.Column(
        'user_type', sa.Enum('ADMIN', 'MEMBER', name='usertype'),
        nullable=False, server_default='MEMBER',
    ))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('shop_owners', 'user_type')
