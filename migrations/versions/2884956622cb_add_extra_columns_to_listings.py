"""add extra columns to listings

Revision ID: 2884956622cb
Revises: 
Create Date: 2025-05-14 14:25:02.018266

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2884956622cb'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('listings', sa.Column('brand', sa.String(length=255), nullable=True))
    op.add_column('listings', sa.Column('model', sa.String(length=25), nullable=True))
    op.add_column('listings', sa.Column('reference_number', sa.String(length=50), nullable=True))
    op.add_column('listings', sa.Column('movement', sa.String(length=25), nullable=True))
    op.add_column('listings', sa.Column('case_material', sa.String(length=25), nullable=True))
    op.add_column('listings', sa.Column('dial_color', sa.String(length=25), nullable=True))
    op.add_column('listings', sa.Column('dial', sa.String(length=25), nullable=True))
    op.execute(
        """
            CREATE INDEX IF NOT EXISTS idx_listings_model ON listings (model);
            CREATE INDEX IF NOT EXISTS idx_listings_brand ON listings (brand);
        """
    )


def downgrade() -> None:
    op.execute(
        """
               DROP INDEX IF EXISTS idx_listings_model;
               DROP INDEX IF EXISTS idx_listings_brand;
        """
    )
    op.drop_column('listings', 'brand')
    op.drop_column('listings', 'model')
    op.drop_column('listings', 'reference_number')
    op.drop_column('listings', 'movement')
    op.drop_column('listings', 'case_material')
    op.drop_column('listings', 'dial_color')
    op.drop_column('listings', 'dial')
