"""add_document_templates_and_template_fks

Revision ID: ab12f8fb0bc4
Revises: ab2225958438
Create Date: 2026-04-03 11:05:33.471679

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ab12f8fb0bc4'
down_revision: Union[str, Sequence[str], None] = 'ab2225958438'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Hardcoded UUIDs for system templates (deterministic across environments)
SYSTEM_SOP_TEMPLATE_ID = "00000000-0000-4000-a000-000000000001"
SYSTEM_BR_TEMPLATE_ID = "00000000-0000-4000-a000-000000000002"

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument"
    ".wordprocessingml.document"
)


def upgrade() -> None:
    # 1. Create document_templates table
    op.create_table(
        "document_templates",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id"),
            nullable=True,
        ),
        sa.Column(
            "uploaded_by_id",
            sa.UUID(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("template_type", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
        ),
        sa.Column(
            "is_system", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "is_default", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "status", sa.String(), server_default="ACTIVE", nullable=False
        ),
        sa.Column(
            "archived_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "archived_by_id",
            sa.UUID(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )

    # 2. Seed system default templates
    op.execute(f"""
        INSERT INTO document_templates
            (id, name, description, template_type, file_path,
             original_filename, mime_type, file_size_bytes,
             is_system, is_default, status)
        VALUES
            ('{SYSTEM_SOP_TEMPLATE_ID}',
             'Batchrite SOP Default',
             'Built-in SOP document template matching the original Batchrite format.',
             'SOP',
             'system/document_templates/sop_default.docx',
             'sop_default.docx',
             '{DOCX_MIME}',
             0,
             true, true, 'ACTIVE'),
            ('{SYSTEM_BR_TEMPLATE_ID}',
             'Batchrite Batch Record Default',
             'Built-in batch record template matching the original Batchrite format.',
             'BATCH_RECORD',
             'system/document_templates/batch_record_default.docx',
             'batch_record_default.docx',
             '{DOCX_MIME}',
             0,
             true, true, 'ACTIVE')
    """)

    # 3. Add FK columns to organizations
    op.add_column(
        "organizations",
        sa.Column(
            "default_sop_template_id",
            sa.UUID(),
            sa.ForeignKey("document_templates.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "default_batch_record_template_id",
            sa.UUID(),
            sa.ForeignKey("document_templates.id"),
            nullable=True,
        ),
    )

    # 4. Add FK columns to projects
    op.add_column(
        "projects",
        sa.Column(
            "default_sop_template_id",
            sa.UUID(),
            sa.ForeignKey("document_templates.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "default_batch_record_template_id",
            sa.UUID(),
            sa.ForeignKey("document_templates.id"),
            nullable=True,
        ),
    )

    # 5. Add FK columns to protocols
    op.add_column(
        "protocols",
        sa.Column(
            "sop_template_id",
            sa.UUID(),
            sa.ForeignKey("document_templates.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "protocols",
        sa.Column(
            "batch_record_template_id",
            sa.UUID(),
            sa.ForeignKey("document_templates.id"),
            nullable=True,
        ),
    )

    # 6. Add FK columns to protocol_versions
    op.add_column(
        "protocol_versions",
        sa.Column(
            "sop_template_id",
            sa.UUID(),
            sa.ForeignKey("document_templates.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "protocol_versions",
        sa.Column(
            "batch_record_template_id",
            sa.UUID(),
            sa.ForeignKey("document_templates.id"),
            nullable=True,
        ),
    )

    # 7. Backfill all existing rows with system defaults
    op.execute(
        f"UPDATE organizations "
        f"SET default_sop_template_id = '{SYSTEM_SOP_TEMPLATE_ID}', "
        f"    default_batch_record_template_id = '{SYSTEM_BR_TEMPLATE_ID}'"
    )
    op.execute(
        f"UPDATE protocols "
        f"SET sop_template_id = '{SYSTEM_SOP_TEMPLATE_ID}', "
        f"    batch_record_template_id = '{SYSTEM_BR_TEMPLATE_ID}'"
    )
    op.execute(
        f"UPDATE protocol_versions "
        f"SET sop_template_id = '{SYSTEM_SOP_TEMPLATE_ID}', "
        f"    batch_record_template_id = '{SYSTEM_BR_TEMPLATE_ID}'"
    )


def downgrade() -> None:
    # Remove FK columns
    op.drop_column("protocol_versions", "batch_record_template_id")
    op.drop_column("protocol_versions", "sop_template_id")
    op.drop_column("protocols", "batch_record_template_id")
    op.drop_column("protocols", "sop_template_id")
    op.drop_column("projects", "default_batch_record_template_id")
    op.drop_column("projects", "default_sop_template_id")
    op.drop_column("organizations", "default_batch_record_template_id")
    op.drop_column("organizations", "default_sop_template_id")

    # Drop table
    op.drop_table("document_templates")
