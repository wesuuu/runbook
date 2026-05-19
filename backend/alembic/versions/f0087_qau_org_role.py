"""Add QAU to allowed org_member roles

Revision ID: f0087_qau_org_role
Revises: f0044_glp_signoffs
Create Date: 2026-05-18

Adds 'QAU' to the ck_org_member_roles CHECK constraint so org members can
hold the Quality Assurance Unit role (21 CFR Part 58 §58.35). The role is
used by GLP-driven protocol approval to resolve who can sign off as QAU
when a protocol's glpSettings.qau_mode is ANY_ORG_QAU.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f0087_qau_org_role"
down_revision: Union[str, Sequence[str], None] = "f0044_glp_signoffs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # f0088_sites_equipment already added QAU + SITE_MANAGER to the
    # constraint. Re-create idempotently so the constraint state matches
    # this revision's declared intent even if the upstream migration is
    # ever loosened.
    op.execute(
        "ALTER TABLE organization_members "
        "DROP CONSTRAINT IF EXISTS ck_org_member_roles"
    )
    op.create_check_constraint(
        "ck_org_member_roles",
        "organization_members",
        "roles <@ ARRAY['ADMIN','BILLING','MEMBER',"
        "'PROTOCOL_APPROVER','QAU','SITE_MANAGER']::varchar[]",
    )


def downgrade() -> None:
    # Strip any QAU values so the tighter constraint can be reinstalled
    # without violating existing rows. SITE_MANAGER stays because the
    # previous revision (f0088_sites_equipment) introduced it.
    op.execute(
        "UPDATE organization_members "
        "SET roles = array_remove(roles, 'QAU') "
        "WHERE 'QAU' = ANY(roles)"
    )
    op.execute(
        "ALTER TABLE organization_members "
        "DROP CONSTRAINT IF EXISTS ck_org_member_roles"
    )
    op.create_check_constraint(
        "ck_org_member_roles",
        "organization_members",
        "roles <@ ARRAY['ADMIN','BILLING','MEMBER',"
        "'PROTOCOL_APPROVER','SITE_MANAGER']::varchar[]",
    )
