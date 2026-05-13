"""td-0085 docling document columns

Revision ID: f0041_docling_document_columns
Revises: f0040
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa

revision = "f0041_docling_document_columns"
down_revision = "f0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_format", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("stored_markdown", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("images_dir", sa.String(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "refinement_status",
            sa.String(),
            nullable=False,
            server_default="NOT_REQUIRED",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "refinement_flags",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column("documents", sa.Column("ocr_engine", sa.String(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("refined_by_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_documents_refined_by_id_users",
        "documents",
        "users",
        ["refined_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "documents",
        sa.Column("refined_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_constraint("fk_documents_refined_by_id_users", "documents", type_="foreignkey")
    op.drop_column("documents", "refined_at")
    op.drop_column("documents", "refined_by_id")
    op.drop_column("documents", "ocr_engine")
    op.drop_column("documents", "refinement_flags")
    op.drop_column("documents", "refinement_status")
    op.drop_column("documents", "images_dir")
    op.drop_column("documents", "stored_markdown")
    op.drop_column("documents", "source_format")
