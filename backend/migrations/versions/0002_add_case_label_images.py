"""add case label images

Revision ID: 0002_add_case_label_images
Revises: 0001_initial_schema
Create Date: 2026-06-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_case_label_images"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("label_images", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "label_images")
