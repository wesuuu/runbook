"""Tests for remaining Phase 1 acceptance criteria:

- Run completion with unanalyzed images (allows but warns)
- PENDING_IMAGE_ANALYSIS notification on completion with unanalyzed images
- Dashboard pending_analyses field
"""
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import RunImage, ImageConversation
from app.models.notifications import Notification
from app.models.science import Project, Protocol, Run, RunStatus


# ── Fixtures ─────────────────────────────────────────────────────────

TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05"
    b"\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06"
    b"\x13Qa\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br"
    b"\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcde"
    b"fghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95"
    b"\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2"
    b"\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8"
    b"\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4"
    b"\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\xa8\xa3\x8a\x00\xff\xd9"
)

SAMPLE_GRAPH = {
    "nodes": [
        {
            "id": "step-1",
            "type": "unitOp",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": "Cell Count",
                "category": "Analysis",
                "paramSchema": {
                    "type": "object",
                    "properties": {
                        "viable_cell_density": {
                            "type": "number",
                            "title": "Viable Cell Density",
                        },
                    },
                },
            },
        }
    ],
    "edges": [],
}


@pytest_asyncio.fixture
async def active_run_with_completed_step(
    db_session: AsyncSession, test_project: Project
) -> Run:
    """Create an ACTIVE run with step-1 already completed in execution_data."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        graph=SAMPLE_GRAPH,
    )
    db_session.add(protocol)
    await db_session.flush()

    run = Run(
        name="Test Run",
        project_id=test_project.id,
        protocol_id=protocol.id,
        status=RunStatus.ACTIVE,
        graph=SAMPLE_GRAPH,
        execution_data={
            "step-1": {
                "status": "completed",
                "results": {"viable_cell_density": 2400000.0},
            }
        },
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.fixture
def tmp_image_storage(tmp_path: Path):
    with patch(
        "app.api.endpoints.ai._get_storage_path",
        return_value=str(tmp_path),
    ):
        yield tmp_path


# ── Run completion with unanalyzed images ────────────────────────────


@pytest.mark.asyncio
async def test_complete_run_with_unanalyzed_images_succeeds(
    client: AsyncClient,
    auth_headers: dict,
    active_run_with_completed_step: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """Run completion should succeed even with unanalyzed images."""
    run = active_run_with_completed_step

    # Upload an image (no analysis)
    await client.post(
        f"/ai/runs/{run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )

    # Complete the run — should succeed
    resp = await client.put(
        f"/science/runs/{run.id}",
        json={
            "status": "COMPLETED",
            "execution_data": run.execution_data,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_complete_run_with_unanalyzed_images_creates_notification(
    client: AsyncClient,
    auth_headers: dict,
    active_run_with_completed_step: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
    test_user,
):
    """Completing a run with unanalyzed images should create a
    PENDING_IMAGE_ANALYSIS notification."""
    run = active_run_with_completed_step

    # Upload an image (no analysis)
    await client.post(
        f"/ai/runs/{run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )

    # Complete the run
    await client.put(
        f"/science/runs/{run.id}",
        json={
            "status": "COMPLETED",
            "execution_data": run.execution_data,
        },
        headers=auth_headers,
    )

    # Check that a PENDING_IMAGE_ANALYSIS notification was created
    result = await db_session.execute(
        select(Notification).where(
            Notification.event_type == "PENDING_IMAGE_ANALYSIS",
            Notification.entity_id == run.id,
        )
    )
    notif = result.scalar_one_or_none()
    assert notif is not None
    assert "unanalyzed" in notif.message.lower()


@pytest.mark.asyncio
async def test_complete_run_all_images_analyzed_no_notification(
    client: AsyncClient,
    auth_headers: dict,
    active_run_with_completed_step: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
    test_user,
):
    """No PENDING_IMAGE_ANALYSIS notification when all images are analyzed."""
    run = active_run_with_completed_step

    # Upload and create a conversation (analyzed)
    upload_resp = await client.post(
        f"/ai/runs/{run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    image_id = upload_resp.json()["id"]

    conv = ImageConversation(
        image_id=uuid.UUID(image_id),
        messages=[{"role": "assistant", "content": "done"}],
        extracted_values={},
        status="confirmed",
    )
    db_session.add(conv)
    await db_session.flush()

    # Complete the run
    await client.put(
        f"/science/runs/{run.id}",
        json={
            "status": "COMPLETED",
            "execution_data": run.execution_data,
        },
        headers=auth_headers,
    )

    # No PENDING_IMAGE_ANALYSIS notification should exist
    result = await db_session.execute(
        select(Notification).where(
            Notification.event_type == "PENDING_IMAGE_ANALYSIS",
            Notification.entity_id == run.id,
        )
    )
    assert result.scalar_one_or_none() is None


# ── Dashboard pending_analyses ───────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_includes_pending_analyses(
    client: AsyncClient,
    auth_headers: dict,
    active_run_with_completed_step: Run,
    tmp_image_storage: Path,
    test_org,
    db_session: AsyncSession,
):
    """Dashboard should include pending_analyses count."""
    run = active_run_with_completed_step

    # Upload 2 images, no analysis
    for i in range(2):
        await client.post(
            f"/ai/runs/{run.id}/steps/step-1/images",
            files={"file": (f"photo{i}.jpg", TINY_JPEG, "image/jpeg")},
            headers=auth_headers,
        )

    resp = await client.get(
        f"/dashboard?org_id={test_org.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    pa = data.get("pending_analyses")
    assert pa is not None
    assert pa["total_images"] == 2
    assert pa["total_runs"] == 1
