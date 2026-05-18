"""f0088 add sites and extend equipment

Revision ID: f0088_sites_equipment
Revises: f0044_glp_signoffs
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ARRAY


revision = "f0088_sites_equipment"
down_revision = "f0044_glp_signoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. sites
    op.create_table(
        "sites",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("is_default", sa.Boolean(),
                  server_default=sa.text("false"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("archive_reason", sa.Text()),
        sa.Column("created_by_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sites_org", "sites", ["organization_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_sites_org_name ON sites (organization_id, name) "
        "WHERE archived_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_sites_org_is_default ON sites (organization_id) "
        "WHERE is_default = true AND archived_at IS NULL"
    )

    # 2. equipment new columns
    op.add_column("equipment", sa.Column("site_id", PG_UUID(as_uuid=True),
                                        sa.ForeignKey("sites.id", ondelete="RESTRICT")))
    op.add_column("equipment", sa.Column("created_by_id", PG_UUID(as_uuid=True),
                                        sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("equipment", sa.Column("manufacturer", sa.String(120)))
    op.add_column("equipment", sa.Column("model", sa.String(120)))
    # serial_number, last_calibration_date, next_calibration_date already added by f0044
    op.add_column("equipment", sa.Column("status", sa.String(20),
                                        server_default="ACTIVE", nullable=False))
    op.add_column("equipment", sa.Column("install_date", sa.Date()))
    op.add_column("equipment", sa.Column("next_calibration_due", sa.Date()))
    op.add_column("equipment", sa.Column("room", sa.String(120)))
    op.add_column("equipment", sa.Column("tags", ARRAY(sa.String()),
                                        server_default=sa.text("ARRAY[]::varchar[]"),
                                        nullable=False))
    op.add_column("equipment", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("equipment", sa.Column("archived_by_id", PG_UUID(as_uuid=True),
                                        sa.ForeignKey("users.id", ondelete="SET NULL")))

    # 3. Backfill: every org gets a Default Site (eager).
    op.execute("""
        INSERT INTO sites (id, organization_id, name, description,
                           is_default, created_at, updated_at)
        SELECT gen_random_uuid(), o.id, 'Default Site',
               'Auto-created on F-0088 migration', true, NOW(), NOW()
        FROM organizations o
        WHERE NOT EXISTS (
            SELECT 1 FROM sites s
            WHERE s.organization_id = o.id AND s.is_default = true
              AND s.archived_at IS NULL
        )
    """)
    op.execute("""
        UPDATE equipment e
        SET site_id = s.id
        FROM sites s
        WHERE s.organization_id = e.organization_id
          AND s.is_default = true
          AND s.archived_at IS NULL
          AND e.site_id IS NULL
    """)

    op.alter_column("equipment", "site_id", nullable=False)
    op.create_index("ix_equipment_site", "equipment", ["site_id"])
    op.create_index("ix_equipment_org_status", "equipment", ["organization_id", "status"])

    # 4. equipment_attachments
    op.create_table(
        "equipment_attachments",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("equipment_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_equipment_attachments_eq", "equipment_attachments", ["equipment_id"])

    # 5. OrganizationMember CHECK constraint
    op.execute("ALTER TABLE organization_members DROP CONSTRAINT IF EXISTS ck_organization_members_roles_valid")
    op.execute(
        "ALTER TABLE organization_members ADD CONSTRAINT ck_organization_members_roles_valid "
        "CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER','SITE_MANAGER']::varchar[])"
    )

    # 6. site_manager_grants
    op.create_table(
        "site_manager_grants",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("site_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("sites.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("granted_by_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_site_manager_grants_site", "site_manager_grants", ["site_id"])
    op.create_index("ix_site_manager_grants_user", "site_manager_grants", ["user_id"])
    op.create_index("ix_site_manager_grants_org", "site_manager_grants", ["organization_id"])
    op.create_index(
        "uq_site_manager_grants_site_user",
        "site_manager_grants", ["site_id", "user_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_site_manager_grants_site_user", "site_manager_grants")
    op.drop_index("ix_site_manager_grants_org", "site_manager_grants")
    op.drop_index("ix_site_manager_grants_user", "site_manager_grants")
    op.drop_index("ix_site_manager_grants_site", "site_manager_grants")
    op.drop_table("site_manager_grants")

    op.execute("ALTER TABLE organization_members DROP CONSTRAINT IF EXISTS ck_organization_members_roles_valid")
    op.execute(
        "ALTER TABLE organization_members ADD CONSTRAINT ck_organization_members_roles_valid "
        "CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER']::varchar[])"
    )

    op.drop_index("ix_equipment_attachments_eq", "equipment_attachments")
    op.drop_table("equipment_attachments")

    op.drop_index("ix_equipment_org_status", "equipment")
    op.drop_index("ix_equipment_site", "equipment")
    # serial_number, last_calibration_date, next_calibration_date dropped by f0044 downgrade
    for col in ("archived_by_id", "archived_at", "tags", "room",
                "next_calibration_due", "install_date",
                "status", "model", "manufacturer",
                "created_by_id", "site_id"):
        op.drop_column("equipment", col)

    op.execute("DROP INDEX IF EXISTS uq_sites_org_is_default")
    op.execute("DROP INDEX IF EXISTS uq_sites_org_name")
    op.drop_index("ix_sites_org", "sites")
    op.drop_table("sites")
