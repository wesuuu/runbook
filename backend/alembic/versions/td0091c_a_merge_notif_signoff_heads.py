"""TD-0091c: merge notif-retention and signoff heads.

Revision ID: td0091c_a_merge
Revises: 3cbfb1725385, acc00af3cd19
Create Date: 2026-05-22
"""

from typing import Sequence, Union

revision: str = "td0091c_a_merge"
down_revision: Union[str, Sequence[str], None] = ("3cbfb1725385", "acc00af3cd19")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
