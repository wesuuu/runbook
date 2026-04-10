"""add batch_record_imports table

Revision ID: 6ec61c5f91b8
Revises: 8e77e851dcbb
Create Date: 2026-04-04 14:00:15.001917

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = '6ec61c5f91b8'
down_revision: Union[str, Sequence[str], None] = '8e77e851dcbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_record_imports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("uploaded_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="EXTRACTING"),
        sa.Column("original_filename", sa.String, nullable=False),
        sa.Column("mime_type", sa.String, nullable=False),
        sa.Column("file_path", sa.String, nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("extraction_result", JSONB, nullable=True),
        sa.Column("extraction_model", sa.String, nullable=True),
        sa.Column("protocol_id", UUID(as_uuid=True), sa.ForeignKey("protocols.id"), nullable=False),
        sa.Column("reviewed_data", JSONB, nullable=True),
        sa.Column("created_run_id", UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("error_message", sa.String, nullable=True),
    )
    op.create_index("ix_bri_org_status", "batch_record_imports", ["org_id", "status"])
    op.create_index("ix_bri_project_created", "batch_record_imports", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_bri_project_created", table_name="batch_record_imports")
    op.drop_index("ix_bri_org_status", table_name="batch_record_imports")
    op.drop_table("batch_record_imports")
