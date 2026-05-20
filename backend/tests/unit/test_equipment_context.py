"""Unit tests for the equipment-context builder."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.models.iam import Organization
from app.models.sites import Site
from app.services.protocols.equipment_context import build_equipment_context


async def _make_org(db_session: AsyncSession) -> Organization:
    org = Organization(name="Acme")
    db_session.add(org)
    await db_session.flush()
    return org


async def _make_org_with_site(
    db_session: AsyncSession,
) -> tuple[Organization, Site]:
    org = await _make_org(db_session)
    site = Site(organization_id=org.id, name="HQ", is_default=True)
    db_session.add(site)
    await db_session.flush()
    return org, site


async def test_build_equipment_context_flattens_assigned_equipment(
    db_session: AsyncSession,
):
    org, site = await _make_org_with_site(db_session)
    eq1 = Equipment(
        organization_id=org.id,
        site_id=site.id,
        name="Sartorius Bioreactor",
        description="5L stirred-tank, single-use",
    )
    eq2 = Equipment(
        organization_id=org.id,
        site_id=site.id,
        name="pH Probe",
        description="Mettler Toledo InPro 3250i",
    )
    db_session.add_all([eq1, eq2])
    await db_session.flush()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {
                            "equipment_id": str(eq1.id),
                            "local_id": "E-001",
                            "shareable": False,
                        },
                        {
                            "equipment_id": str(eq2.id),
                            "local_id": "E-002",
                            "shareable": False,
                        },
                    ],
                },
            },
        ],
    }

    ctx, warnings = await build_equipment_context(db_session, org.id, graph)

    assert ctx == {
        "E-001_name": "Sartorius Bioreactor",
        "E-001_description": "5L stirred-tank, single-use",
        "E-002_name": "pH Probe",
        "E-002_description": "Mettler Toledo InPro 3250i",
    }
    assert warnings == []


async def test_build_equipment_context_skips_entries_without_local_id(
    db_session: AsyncSession,
):
    org, site = await _make_org_with_site(db_session)
    eq = Equipment(organization_id=org.id, site_id=site.id, name="X", description="d")
    db_session.add(eq)
    await db_session.flush()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {"equipment_id": str(eq.id), "shareable": False},
                    ],
                },
            },
        ],
    }
    ctx, warnings = await build_equipment_context(db_session, org.id, graph)
    assert ctx == {}
    assert warnings == []


async def test_build_equipment_context_warns_on_duplicate_local_id(
    db_session: AsyncSession,
):
    org, site = await _make_org_with_site(db_session)
    a = Equipment(organization_id=org.id, site_id=site.id, name="A", description="a")
    b = Equipment(organization_id=org.id, site_id=site.id, name="B", description="b")
    db_session.add_all([a, b])
    await db_session.flush()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {
                            "equipment_id": str(a.id),
                            "local_id": "E-001",
                            "shareable": False,
                        },
                    ],
                },
            },
            {
                "id": "n2",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {
                            "equipment_id": str(b.id),
                            "local_id": "E-001",
                            "shareable": False,
                        },
                    ],
                },
            },
        ],
    }
    ctx, warnings = await build_equipment_context(db_session, org.id, graph)
    assert ctx["E-001_name"] == "A"
    assert any("E-001" in w and "duplicate" in w.lower() for w in warnings)


async def test_build_equipment_context_warns_when_equipment_missing(
    db_session: AsyncSession,
):
    org = await _make_org(db_session)
    bogus = uuid.uuid4()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {
                            "equipment_id": str(bogus),
                            "local_id": "E-001",
                            "shareable": False,
                        },
                    ],
                },
            },
        ],
    }
    ctx, warnings = await build_equipment_context(db_session, org.id, graph)
    assert ctx == {}
    assert any("E-001" in w for w in warnings)


async def test_build_equipment_context_handles_swimlane_children(
    db_session: AsyncSession,
):
    org, site = await _make_org_with_site(db_session)
    eq = Equipment(organization_id=org.id, site_id=site.id, name="N", description="d")
    db_session.add(eq)
    await db_session.flush()

    graph = {
        "nodes": [
            {"id": "s1", "type": "swimLane", "data": {}},
            {
                "id": "n1",
                "type": "unitOp",
                "parentId": "s1",
                "data": {
                    "equipment": [
                        {
                            "equipment_id": str(eq.id),
                            "local_id": "E-001",
                            "shareable": False,
                        },
                    ],
                },
            },
        ],
    }
    ctx, _ = await build_equipment_context(db_session, org.id, graph)
    assert ctx["E-001_name"] == "N"


async def test_build_equipment_context_handles_none_graph(
    db_session: AsyncSession,
):
    org = await _make_org(db_session)
    ctx, warnings = await build_equipment_context(db_session, org.id, None)
    assert ctx == {}
    assert warnings == []
