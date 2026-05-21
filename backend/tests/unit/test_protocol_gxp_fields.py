"""Unit tests for QA-0008 Protocol GxP metadata fields."""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.protocols import Protocol, ProtocolVersion


@pytest.mark.asyncio
async def test_protocol_has_gxp_metadata_columns(db_session: AsyncSession, test_org):
    p = Protocol(
        name="P",
        organization_id=test_org.id,
        owner_org_id=test_org.id,
        slug="p-gxp",
        graph={},
        doc_number="SOP-0001",
        effective_date=date(2026, 1, 1),
        supersedes_date=date(2025, 1, 1),
        purpose="Establish the procedure for X.",
        scope="Applies to Y.",
        references="ICH Q7.",
        definitions="CIP = clean-in-place.",
    )
    db_session.add(p)
    await db_session.flush()
    await db_session.refresh(p)

    assert p.doc_number == "SOP-0001"
    assert p.effective_date == date(2026, 1, 1)
    assert p.supersedes_date == date(2025, 1, 1)
    assert p.purpose.startswith("Establish")
    assert p.scope == "Applies to Y."
    assert p.references == "ICH Q7."
    assert p.definitions.startswith("CIP")


@pytest.mark.asyncio
async def test_protocol_gxp_fields_all_nullable(db_session: AsyncSession, test_org):
    p = Protocol(name="bare", organization_id=test_org.id, owner_org_id=test_org.id, slug="bare", graph={})
    db_session.add(p)
    await db_session.flush()
    await db_session.refresh(p)
    assert p.doc_number is None
    assert p.effective_date is None
    assert p.purpose is None


@pytest.mark.asyncio
async def test_protocol_version_snapshots_gxp_fields(
    db_session: AsyncSession, test_org
):
    pv = ProtocolVersion(
        protocol_id=None,  # leaving null for unit test; integration would set
        version_number=1,
        graph={},
        name="snap",
        doc_number="SOP-0001",
        effective_date=date(2026, 1, 1),
        supersedes_date=None,
        purpose="p",
        scope="s",
        references="r",
        definitions="d",
    )
    # Skip persistence; this asserts the constructor accepts the kwargs.
    assert pv.doc_number == "SOP-0001"
    assert pv.purpose == "p"
