"""remove unique constraint from listing url

Revision ID: a5eaf0d66110
Revises: 2884956622cb
Create Date: 2025-05-14 14:38:55.027776

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5eaf0d66110'
down_revision: Union[str, None] = '2884956622cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('listings_listing_url_key', 'listings', type_='unique')


def downgrade() -> None:
    pass
