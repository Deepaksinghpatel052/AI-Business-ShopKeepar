"""add password reset code fields to shop_owners

Revision ID: 2a383a8b5b1a
Revises: bf64f6344bd0
Create Date: 2026-08-20 23:58:37.143602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a383a8b5b1a'
down_revision: Union[str, Sequence[str], None] = 'bf64f6344bd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: autogenerate also proposed dropping 'transactions' and 'email_queue' —
    # those tables have no SQLAlchemy model yet (pre-existing, unrelated to this change),
    # so those drops were removed from this migration.
    op.add_column('shop_owners', sa.Column('reset_code_hash', sa.String(length=255), nullable=True))
    op.add_column('shop_owners', sa.Column('reset_code_expires_at', sa.DateTime(), nullable=True))
    op.add_column('shop_owners', sa.Column('reset_code_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('shop_owners', sa.Column('reset_code_last_sent_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('shop_owners', 'reset_code_last_sent_at')
    op.drop_column('shop_owners', 'reset_code_attempts')
    op.drop_column('shop_owners', 'reset_code_expires_at')
    op.drop_column('shop_owners', 'reset_code_hash')
