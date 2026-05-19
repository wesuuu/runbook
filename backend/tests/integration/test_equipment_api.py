"""Integration tests for /equipment router — field-level permission gate + attachments.

Permission matrix (per spec):
  - GET (list/detail):  any MEMBER
  - POST (create):      any MEMBER; restricted fields silently dropped unless SITE_MANAGER+grant or ADMIN
  - PATCH (update):     any MEMBER for unrestricted fields; SITE_MANAGER+grant or ADMIN for restricted
  - DELETE (archive):   SITE_MANAGER (additive) OR ADMIN
  - Attachments POST:   SITE_MANAGER (additive) OR ADMIN
  - Attachments GET:    any MEMBER
  - /equipment/tags:    any MEMBER
"""

import pytest
from httpx import AsyncClient

# ── list + detail ─────────────────────────────────────────────────────────────


async def test_list_equipment_member(
    authed_member_client: AsyncClient,
    default_site_id: str,
    member_owned_equipment_id: str,
):
    """MEMBER can list equipment for their org."""
    resp = await authed_member_client.get("/equipment")
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert member_owned_equipment_id in ids


async def test_list_equipment_filter_site(
    authed_member_client: AsyncClient,
    default_site_id: str,
    member_owned_equipment_id: str,
    equipment_on_unmanaged_site_id: str,
    managed_site,
    unmanaged_site,
):
    """site_id filter narrows results."""
    resp = await authed_member_client.get(
        "/equipment", params={"site_id": str(managed_site.id)}
    )
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert member_owned_equipment_id in ids
    assert equipment_on_unmanaged_site_id not in ids


async def test_get_equipment_member(
    authed_member_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """MEMBER can retrieve a single equipment item."""
    resp = await authed_member_client.get(f"/equipment/{member_owned_equipment_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == member_owned_equipment_id


# ── create ────────────────────────────────────────────────────────────────────


async def test_create_equipment_member_unrestricted(
    authed_member_client: AsyncClient,
    default_site_id: str,
):
    """MEMBER can create equipment; unrestricted fields are persisted."""
    resp = await authed_member_client.post(
        "/equipment",
        json={
            "name": "Pipette Set",
            "site_id": default_site_id,
            "equipment_type": "pipette",
            "room": "Lab A",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Pipette Set"
    assert data["equipment_type"] == "pipette"
    assert data["room"] == "Lab A"


async def test_create_equipment_member_restricted_fields_silently_dropped(
    authed_member_client: AsyncClient,
    default_site_id: str,
):
    """MEMBER cannot set restricted fields on create — they are silently dropped to defaults."""
    resp = await authed_member_client.post(
        "/equipment",
        json={
            "name": "Centrifuge",
            "site_id": default_site_id,
            "manufacturer": "Eppendorf",
            "serial_number": "SN-001",
            "status": "MAINTENANCE",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    # Restricted fields should be cleared / defaulted
    assert data["manufacturer"] is None
    assert data["serial_number"] is None
    assert data["status"] == "ACTIVE"


async def test_create_equipment_site_manager_with_grant_sets_restricted(
    authed_site_manager_client: AsyncClient,
    managed_site,
):
    """SITE_MANAGER with a grant on the site can set restricted fields on create."""
    resp = await authed_site_manager_client.post(
        "/equipment",
        json={
            "name": "Bioreactor",
            "site_id": str(managed_site.id),
            "manufacturer": "Sartorius",
            "serial_number": "BR-2024-001",
            "status": "ACTIVE",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["manufacturer"] == "Sartorius"
    assert data["serial_number"] == "BR-2024-001"


async def test_create_equipment_admin_sets_restricted(
    authed_admin_client: AsyncClient,
    default_site_id: str,
):
    """ADMIN can always set restricted fields."""
    resp = await authed_admin_client.post(
        "/equipment",
        json={
            "name": "Autoclave",
            "site_id": default_site_id,
            "manufacturer": "Getinge",
            "serial_number": "AC-9000",
            "status": "MAINTENANCE",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["manufacturer"] == "Getinge"
    assert data["serial_number"] == "AC-9000"
    assert data["status"] == "MAINTENANCE"


# ── patch ─────────────────────────────────────────────────────────────────────


async def test_patch_equipment_member_unrestricted_fields(
    authed_member_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """MEMBER can patch unrestricted fields (name, description, room, etc.)."""
    resp = await authed_member_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"name": "Renamed", "room": "Room 5"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Renamed"
    assert data["room"] == "Room 5"


async def test_patch_equipment_member_restricted_field_forbidden(
    authed_member_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """MEMBER cannot patch restricted fields — 403 with EQUIPMENT_FIELD_RESTRICTED."""
    resp = await authed_member_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"manufacturer": "ChangeAttempt"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["detail"]["code"] == "EQUIPMENT_FIELD_RESTRICTED"
    assert "manufacturer" in body["detail"]["fields"]


async def test_patch_equipment_restricted_roundtrip_noop(
    authed_member_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """Round-tripping a restricted field with its CURRENT value is a no-op — no 403."""
    # First retrieve the current value
    get_resp = await authed_member_client.get(f"/equipment/{member_owned_equipment_id}")
    assert get_resp.status_code == 200
    current_manufacturer = get_resp.json()["manufacturer"]  # None by default

    # PATCH with the same value should not 403
    resp = await authed_member_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"manufacturer": current_manufacturer},
    )
    assert resp.status_code == 200


async def test_patch_equipment_site_manager_with_grant_restricted(
    authed_site_manager_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """SITE_MANAGER with grant on the equipment's site can edit restricted fields."""
    resp = await authed_site_manager_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"manufacturer": "NewManuf", "status": "MAINTENANCE"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["manufacturer"] == "NewManuf"
    assert data["status"] == "MAINTENANCE"


async def test_patch_equipment_site_manager_no_grant_forbidden(
    authed_site_manager_client: AsyncClient,
    equipment_on_unmanaged_site_id: str,
):
    """SITE_MANAGER without a grant on the equipment's site cannot edit restricted fields."""
    resp = await authed_site_manager_client.patch(
        f"/equipment/{equipment_on_unmanaged_site_id}",
        json={"manufacturer": "NoGrant"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["detail"]["code"] == "EQUIPMENT_FIELD_RESTRICTED"


async def test_patch_equipment_move_site_forbidden_without_grant(
    authed_site_manager_client: AsyncClient,
    member_owned_equipment_id: str,
    unmanaged_site,
):
    """Moving equipment to a site the SITE_MANAGER has no grant on → SITE_MOVE_FORBIDDEN."""
    resp = await authed_site_manager_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"site_id": str(unmanaged_site.id)},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["detail"]["code"] == "SITE_MOVE_FORBIDDEN"
    assert "missing_grants" in body["detail"]


async def test_patch_archived_equipment_blocked(
    authed_admin_client: AsyncClient,
    archived_equipment_id: str,
):
    """Writing to archived equipment returns 400 EQUIPMENT_ARCHIVED."""
    resp = await authed_admin_client.patch(
        f"/equipment/{archived_equipment_id}",
        json={"name": "Cannot Update"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "EQUIPMENT_ARCHIVED"


# ── delete (archive) ──────────────────────────────────────────────────────────


async def test_delete_equipment_member_forbidden(
    authed_member_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """Plain MEMBER cannot archive equipment — 403."""
    resp = await authed_member_client.delete(f"/equipment/{member_owned_equipment_id}")
    assert resp.status_code == 403


async def test_delete_equipment_site_manager_with_grant(
    authed_site_manager_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """SITE_MANAGER with a grant can archive equipment on that site."""
    resp = await authed_site_manager_client.delete(
        f"/equipment/{member_owned_equipment_id}"
    )
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is not None


async def test_delete_equipment_admin(
    authed_admin_client: AsyncClient,
    default_site_id: str,
):
    """ADMIN can archive any equipment."""
    # Create equipment to archive
    create_resp = await authed_admin_client.post(
        "/equipment",
        json={"name": "ToArchive", "site_id": default_site_id},
    )
    assert create_resp.status_code == 201
    eq_id = create_resp.json()["id"]

    resp = await authed_admin_client.delete(f"/equipment/{eq_id}")
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is not None


# ── tags ─────────────────────────────────────────────────────────────────────


async def test_list_tags_member(
    authed_member_client: AsyncClient,
    authed_admin_client: AsyncClient,
    default_site_id: str,
):
    """GET /equipment/tags returns distinct tags; any MEMBER can call it."""
    # Seed some equipment with tags
    await authed_admin_client.post(
        "/equipment",
        json={
            "name": "TaggedEq1",
            "site_id": default_site_id,
            "tags": ["incubator", "cell-culture"],
        },
    )
    await authed_admin_client.post(
        "/equipment",
        json={
            "name": "TaggedEq2",
            "site_id": default_site_id,
            "tags": ["incubator", "ro-water"],
        },
    )

    resp = await authed_member_client.get("/equipment/tags")
    assert resp.status_code == 200
    tags = resp.json()
    assert "incubator" in tags
    assert "cell-culture" in tags
    assert "ro-water" in tags
    # Distinct — no duplicates
    assert tags.count("incubator") == 1


# ── attachments ───────────────────────────────────────────────────────────────


async def test_list_attachments_member(
    authed_member_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """Any MEMBER can list attachments (even if empty)."""
    resp = await authed_member_client.get(
        f"/equipment/{member_owned_equipment_id}/attachments"
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_upload_attachment_member_forbidden(
    authed_member_client: AsyncClient,
    member_owned_equipment_id: str,
):
    """Plain MEMBER cannot upload attachments — 403."""
    resp = await authed_member_client.post(
        f"/equipment/{member_owned_equipment_id}/attachments",
        files={"file": ("test.pdf", b"%PDF-stub", "application/pdf")},
    )
    assert resp.status_code == 403


# ── delete attachment ─────────────────────────────────────────────────────────


async def test_delete_attachment_admin(
    authed_admin_client: AsyncClient,
    db_session,
    sample_equipment_attachment,
):
    """ADMIN can delete an existing attachment; row is removed from DB."""
    from app.models.science import EquipmentAttachment

    att_id = str(sample_equipment_attachment.id)
    resp = await authed_admin_client.delete(f"/equipment/attachments/{att_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}
    # Verify the row is gone
    still_there = await db_session.get(
        EquipmentAttachment, sample_equipment_attachment.id
    )
    assert still_there is None


async def test_delete_attachment_not_found(
    authed_admin_client: AsyncClient,
):
    """Unknown attachment id → 404."""
    import uuid as _uuid

    resp = await authed_admin_client.delete(f"/equipment/attachments/{_uuid.uuid4()}")
    assert resp.status_code == 404


async def test_delete_attachment_cross_org_returns_404(
    authed_admin_client: AsyncClient,
    db_session,
    second_org,
    second_user,
    other_org_site,
):
    """Attachment belonging to another org → 404 (not 403)."""
    from app.models.science import Equipment, EquipmentAttachment

    eq = Equipment(
        organization_id=second_org.id,
        name="Other Org Equip",
        site_id=other_org_site.id,
        created_by_id=second_user.id,
    )
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    att = EquipmentAttachment(
        equipment_id=eq.id,
        file_path=(f"{second_org.id}/equipment/{eq.id}/other.pdf"),
        original_filename="other.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        uploaded_by_id=second_user.id,
    )
    db_session.add(att)
    await db_session.commit()
    await db_session.refresh(att)

    resp = await authed_admin_client.delete(f"/equipment/attachments/{att.id}")
    assert resp.status_code == 404


async def test_delete_attachment_member_forbidden(
    authed_member_client: AsyncClient,
    sample_equipment_attachment,
):
    """Plain MEMBER (no SITE_MANAGER, no ADMIN) cannot delete — 403."""
    resp = await authed_member_client.delete(
        f"/equipment/attachments/{sample_equipment_attachment.id}"
    )
    assert resp.status_code == 403
