# backend/alembic/versions/f0091_url_slugs.py
"""F-0091 — add URL slug columns to routed entities.

Revision ID: f0091_url_slugs
Revises: f0087_qau_org_role
"""

from collections import defaultdict

import sqlalchemy as sa
from alembic import op

from app.core.slug import dedupe_slugs, slugify

revision = "f0091_url_slugs"
down_revision = "f0087_qau_org_role"
branch_labels = None
depends_on = None


# (table, name_column, scope_column, unique_index_name)
_TABLES = [
    ("protocols", "name", "owner_org_id", "uq_protocols_owner_org_slug"),
    ("projects", "name", "organization_id", "uq_projects_org_slug"),
    ("runs", "name", "project_id", "uq_runs_project_slug"),
    ("experiments", "name", "project_id", "uq_experiments_project_slug"),
    ("documents", "title", "org_id", "uq_documents_org_slug"),
]


def _backfill_slugs(bind, table, name_column, scope_column):
    """Generate collision-free slugs for every existing row in `table`."""
    rows = bind.execute(
        sa.text(
            f"SELECT id, {name_column} AS nm, {scope_column} AS scope "
            f"FROM {table} ORDER BY created_at ASC, id ASC"
        )
    ).fetchall()
    by_scope = defaultdict(list)
    for row in rows:
        by_scope[row.scope].append((str(row.id), slugify(row.nm or "")))
    for items in by_scope.values():
        for row_id, final_slug in dedupe_slugs(items).items():
            bind.execute(
                sa.text(f"UPDATE {table} SET slug = :slug WHERE id = :id"),
                {"slug": final_slug, "id": row_id},
            )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add columns nullable so existing rows are not rejected.
    op.add_column(
        "protocols", sa.Column("owner_org_id", sa.UUID(as_uuid=True), nullable=True)
    )
    for table, _name, _scope, _idx in _TABLES:
        op.add_column(table, sa.Column("slug", sa.String(length=64), nullable=True))

    # 2. Backfill protocols.owner_org_id (org-scoped row uses its own
    #    organization_id; project-scoped row inherits the project's org).
    op.execute(
        """
        UPDATE protocols p
        SET owner_org_id = COALESCE(
            p.organization_id,
            (SELECT pr.organization_id FROM projects pr WHERE pr.id = p.project_id)
        )
        """
    )

    # 3. Backfill slugs (Python loop — slugify cannot run in pure SQL).
    for table, name_column, scope_column, _idx in _TABLES:
        _backfill_slugs(bind, table, name_column, scope_column)

    # 4. Lock columns down: NOT NULL + FK + unique indexes.
    op.alter_column("protocols", "owner_org_id", nullable=False)
    op.create_foreign_key(
        "fk_protocols_owner_org_id", "protocols", "organizations",
        ["owner_org_id"], ["id"],
    )
    for table, _name, scope_column, idx in _TABLES:
        op.alter_column(table, "slug", nullable=False)
        op.create_unique_constraint(idx, table, [scope_column, "slug"])


def downgrade() -> None:
    for table, _name, _scope, idx in _TABLES:
        op.drop_constraint(idx, table, type_="unique")
        op.drop_column(table, "slug")
    op.drop_constraint("fk_protocols_owner_org_id", "protocols", type_="foreignkey")
    op.drop_column("protocols", "owner_org_id")
