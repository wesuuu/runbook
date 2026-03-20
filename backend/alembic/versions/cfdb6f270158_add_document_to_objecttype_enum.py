"""add_document_to_objecttype_enum

Add DOCUMENT to the ObjectType enum (Python-side only; the DB column
is a plain VARCHAR so no DDL change is needed).

Revision ID: cfdb6f270158
Revises: c689a4e0e61a
Create Date: 2026-03-20 10:49:28.300824

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'cfdb6f270158'
down_revision: Union[str, Sequence[str], None] = 'c689a4e0e61a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No DDL needed — ObjectType is stored as VARCHAR."""
    pass


def downgrade() -> None:
    pass
