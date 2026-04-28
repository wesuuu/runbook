"""Migration sanity test — verifies the columns are present on the actual
DB schema (not just on the model class) after migrations have been applied.
Runs against the fixture-managed test DB.
"""

import pytest
from sqlalchemy import inspect


@pytest.mark.asyncio
async def test_users_table_has_tos_columns(db_session):
    def _inspect(sync_session):
        inspector = inspect(sync_session.bind)
        cols = {c["name"] for c in inspector.get_columns("users")}
        return cols

    cols = await db_session.run_sync(_inspect)
    assert "tos_accepted_at" in cols
    assert "tos_version" in cols


@pytest.mark.asyncio
async def test_organizations_table_has_legal_terms_overridden_column(db_session):
    def _inspect(sync_session):
        inspector = inspect(sync_session.bind)
        cols = {c["name"] for c in inspector.get_columns("organizations")}
        return cols

    cols = await db_session.run_sync(_inspect)
    assert "legal_terms_overridden" in cols
