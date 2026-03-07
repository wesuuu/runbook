import io
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import RunImage, ImageConversation
from app.models.iam import (
    User,
    Organization,
    OrganizationMember,
    ObjectPermission,
    PrincipalType,
    ObjectType,
    PermissionLevel,
)
from app.models.science import Project, Protocol, Run, RunStatus


# ── Fixtures ──────────────────────────────────────────────────────────


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
                            "unit": "cells/mL",
                        },
                        "viability_percent": {
                            "type": "number",
                            "title": "Viability",
                            "unit": "%",
                        },
                    },
                },
            },
        }
    ],
    "edges": [],
}


@pytest_asyncio.fixture
async def test_run(db_session: AsyncSession, test_project: Project) -> Run:
    """Create an ACTIVE run with a graph containing one unit op step."""
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
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.fixture
def tmp_image_storage(tmp_path: Path):
    """Override image storage to a temp directory."""
    with patch(
        "app.api.endpoints.ai._get_storage_path",
        return_value=str(tmp_path),
    ):
        yield tmp_path


# ── Upload Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_image_success(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["run_id"] == str(test_run.id)
    assert data["step_id"] == "step-1"
    assert data["original_filename"] == "photo.jpg"
    assert data["mime_type"] == "image/jpeg"
    assert data["file_size_bytes"] == len(TINY_JPEG)


@pytest.mark.asyncio
async def test_upload_writes_file_to_disk(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    file_path = resp.json()["file_path"]
    full_path = tmp_image_storage / file_path
    assert full_path.exists()
    assert full_path.read_bytes() == TINY_JPEG


@pytest.mark.asyncio
async def test_upload_creates_db_record(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    image_id = resp.json()["id"]

    result = await db_session.execute(
        select(RunImage).where(RunImage.id == uuid.UUID(image_id))
    )
    row = result.scalar_one()
    assert row.run_id == test_run.id
    assert row.step_id == "step-1"
    assert row.mime_type == "image/jpeg"


@pytest.mark.asyncio
async def test_upload_png(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    # Minimal 1x1 PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
        b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("screenshot.png", png_bytes, "image/png")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["mime_type"] == "image/png"
    assert resp.json()["file_path"].endswith(".png")


@pytest.mark.asyncio
async def test_upload_rejects_non_image(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "Unsupported image type" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    # Patch MAX to a tiny value for testing
    with patch("app.api.endpoints.ai.MAX_IMAGE_SIZE_BYTES", 100):
        resp = await client.post(
            f"/ai/runs/{test_run.id}/steps/step-1/images",
            files={"file": ("big.jpg", TINY_JPEG, "image/jpeg")},
            headers=auth_headers,
        )
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_to_nonexistent_run(
    client: AsyncClient,
    auth_headers: dict,
    tmp_image_storage: Path,
):
    fake_id = uuid.uuid4()
    resp = await client.post(
        f"/ai/runs/{fake_id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_to_planned_run_rejected(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    # Set run to PLANNED
    test_run.status = RunStatus.PLANNED
    await db_session.flush()

    resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "ACTIVE" in resp.json()["detail"]


# ── List & Get Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_images_empty(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
):
    resp = await client.get(
        f"/ai/runs/{test_run.id}/images",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_list_images_returns_uploads(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    # Upload two images
    await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo1.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo2.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )

    resp = await client.get(
        f"/ai/runs/{test_run.id}/images",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    filenames = {i["original_filename"] for i in items}
    assert filenames == {"photo1.jpg", "photo2.jpg"}


@pytest.mark.asyncio
async def test_list_images_nonexistent_run(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.get(
        f"/ai/runs/{uuid.uuid4()}/images",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_image_detail(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    upload_resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    image_id = upload_resp.json()["id"]

    resp = await client.get(
        f"/ai/runs/{test_run.id}/images/{image_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == image_id
    assert data["conversation"] is None  # No conversation yet


@pytest.mark.asyncio
async def test_get_image_with_conversation(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    upload_resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    image_id = upload_resp.json()["id"]

    # Create a conversation manually
    conv = ImageConversation(
        image_id=uuid.UUID(image_id),
        messages=[{"role": "assistant", "content": "I see a cell count"}],
        extracted_values={"viable_cell_density": 2.4e6},
        status="needs_clarification",
    )
    db_session.add(conv)
    await db_session.flush()

    resp = await client.get(
        f"/ai/runs/{test_run.id}/images/{image_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation"] is not None
    assert data["conversation"]["status"] == "needs_clarification"
    assert len(data["conversation"]["messages"]) == 1


@pytest.mark.asyncio
async def test_get_image_not_found(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
):
    resp = await client.get(
        f"/ai/runs/{test_run.id}/images/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404
