"""Tests for Phase 1: Async Image Analysis (F-0002).

Covers:
- parameter_tags field on RunImage
- PUT /ai/runs/{id}/images/{id}/tag endpoint
- POST /ai/runs/{id}/analyze-pending batch endpoint
- GET /ai/runs/{id}/images?analyzed=false filter
"""
import uuid
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import RunImage, ImageConversation
from app.models.science import Project, Protocol, Run, RunStatus
from app.services.ai_vision import ImageAnalysisResult, ExtractedValue


# ── Shared fixtures ──────────────────────────────────────────────────

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

MOCK_ANALYSIS_RESULT = ImageAnalysisResult(
    message="Viable Cell Density: 2.4e6 cells/mL, Viability: 96.2%.",
    extracted_values=[
        ExtractedValue(
            field_key="viable_cell_density",
            field_label="Viable Cell Density",
            value=2400000.0,
            unit="cells/mL",
            confidence=0.95,
        ),
        ExtractedValue(
            field_key="viability_percent",
            field_label="Viability",
            value=96.2,
            unit="%",
            confidence=0.90,
        ),
    ],
    needs_clarification=False,
)


@pytest_asyncio.fixture
async def test_run(db_session: AsyncSession, test_project: Project) -> Run:
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
    with patch(
        "app.api.endpoints.ai._get_storage_path",
        return_value=str(tmp_path),
    ):
        yield tmp_path


async def _upload_image(
    client: AsyncClient,
    auth_headers: dict,
    run_id: uuid.UUID,
    step_id: str = "step-1",
    filename: str = "photo.jpg",
) -> dict:
    """Helper: upload an image and return JSON response."""
    resp = await client.post(
        f"/ai/runs/{run_id}/steps/{step_id}/images",
        files={"file": (filename, TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()


# ── parameter_tags in upload response ────────────────────────────────


@pytest.mark.asyncio
async def test_upload_response_includes_parameter_tags(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    """parameter_tags should be present in upload response (null by default)."""
    data = await _upload_image(client, auth_headers, test_run.id)
    assert "parameter_tags" in data
    assert data["parameter_tags"] is None


# ── PUT /ai/runs/{id}/images/{id}/tag ────────────────────────────────


@pytest.mark.asyncio
async def test_tag_image_sets_parameter_tags(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """Tag endpoint should store parameter_tags on the image."""
    image = await _upload_image(client, auth_headers, test_run.id)

    resp = await client.put(
        f"/ai/runs/{test_run.id}/images/{image['id']}/tag",
        json={"parameter_tags": ["viable_cell_density", "viability_percent"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["parameter_tags"] == ["viable_cell_density", "viability_percent"]

    # Verify in DB
    result = await db_session.execute(
        select(RunImage).where(RunImage.id == uuid.UUID(image["id"]))
    )
    row = result.scalar_one()
    assert row.parameter_tags == ["viable_cell_density", "viability_percent"]


@pytest.mark.asyncio
async def test_tag_image_replaces_existing_tags(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    """Calling tag again should replace, not append."""
    image = await _upload_image(client, auth_headers, test_run.id)

    # Tag first time
    await client.put(
        f"/ai/runs/{test_run.id}/images/{image['id']}/tag",
        json={"parameter_tags": ["viable_cell_density"]},
        headers=auth_headers,
    )

    # Tag second time with different tags
    resp = await client.put(
        f"/ai/runs/{test_run.id}/images/{image['id']}/tag",
        json={"parameter_tags": ["viability_percent"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["parameter_tags"] == ["viability_percent"]


@pytest.mark.asyncio
async def test_tag_image_clear_tags(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    """Passing empty list should clear tags."""
    image = await _upload_image(client, auth_headers, test_run.id)

    await client.put(
        f"/ai/runs/{test_run.id}/images/{image['id']}/tag",
        json={"parameter_tags": ["viable_cell_density"]},
        headers=auth_headers,
    )

    resp = await client.put(
        f"/ai/runs/{test_run.id}/images/{image['id']}/tag",
        json={"parameter_tags": []},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["parameter_tags"] == []


@pytest.mark.asyncio
async def test_tag_nonexistent_image_returns_404(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    resp = await client.put(
        f"/ai/runs/{test_run.id}/images/{uuid.uuid4()}/tag",
        json={"parameter_tags": ["pH"]},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── GET /ai/runs/{id}/images?analyzed filter ─────────────────────────


@pytest.mark.asyncio
async def test_list_images_filter_unanalyzed(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """?analyzed=false should return only images without a conversation."""
    img1 = await _upload_image(
        client, auth_headers, test_run.id, filename="photo1.jpg"
    )
    img2 = await _upload_image(
        client, auth_headers, test_run.id, filename="photo2.jpg"
    )

    # Give img1 a conversation (mark it as analyzed)
    conv = ImageConversation(
        image_id=uuid.UUID(img1["id"]),
        messages=[{"role": "assistant", "content": "Analyzed"}],
        extracted_values={},
        status="analyzed",
    )
    db_session.add(conv)
    await db_session.flush()

    # Filter for unanalyzed
    resp = await client.get(
        f"/ai/runs/{test_run.id}/images?analyzed=false",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == img2["id"]


@pytest.mark.asyncio
async def test_list_images_filter_analyzed(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """?analyzed=true should return only images with a conversation."""
    img1 = await _upload_image(
        client, auth_headers, test_run.id, filename="photo1.jpg"
    )
    img2 = await _upload_image(
        client, auth_headers, test_run.id, filename="photo2.jpg"
    )

    # Give img1 a conversation
    conv = ImageConversation(
        image_id=uuid.UUID(img1["id"]),
        messages=[{"role": "assistant", "content": "Analyzed"}],
        extracted_values={},
        status="analyzed",
    )
    db_session.add(conv)
    await db_session.flush()

    resp = await client.get(
        f"/ai/runs/{test_run.id}/images?analyzed=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == img1["id"]


@pytest.mark.asyncio
async def test_list_images_no_filter_returns_all(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """No filter should return all images (backwards compatible)."""
    await _upload_image(
        client, auth_headers, test_run.id, filename="photo1.jpg"
    )
    img2 = await _upload_image(
        client, auth_headers, test_run.id, filename="photo2.jpg"
    )

    # Give img2 a conversation
    conv = ImageConversation(
        image_id=uuid.UUID(img2["id"]),
        messages=[{"role": "assistant", "content": "test"}],
        extracted_values={},
        status="analyzed",
    )
    db_session.add(conv)
    await db_session.flush()

    resp = await client.get(
        f"/ai/runs/{test_run.id}/images",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


@pytest.mark.asyncio
async def test_list_images_response_includes_parameter_tags(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """List response should include parameter_tags for each image."""
    image = await _upload_image(client, auth_headers, test_run.id)

    # Tag the image
    await client.put(
        f"/ai/runs/{test_run.id}/images/{image['id']}/tag",
        json={"parameter_tags": ["pH"]},
        headers=auth_headers,
    )

    resp = await client.get(
        f"/ai/runs/{test_run.id}/images",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["parameter_tags"] == ["pH"]


# ── POST /ai/runs/{id}/analyze-pending (batch) ──────────────────────


def _mock_analyze(*args, **kwargs):
    return MOCK_ANALYSIS_RESULT


@pytest.mark.asyncio
async def test_analyze_pending_processes_unanalyzed_images(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """Batch analyze should process images that have no conversation."""
    img1 = await _upload_image(
        client, auth_headers, test_run.id, filename="photo1.jpg"
    )
    img2 = await _upload_image(
        client, auth_headers, test_run.id, filename="photo2.jpg"
    )

    # Give img1 a conversation (already analyzed)
    conv = ImageConversation(
        image_id=uuid.UUID(img1["id"]),
        messages=[{"role": "assistant", "content": "done"}],
        extracted_values={},
        status="confirmed",
    )
    db_session.add(conv)
    await db_session.flush()

    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze),
    ) as mock_ai:
        resp = await client.post(
            f"/ai/runs/{test_run.id}/analyze-pending",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["succeeded"] == 1
    assert data["failed"] == 0
    # Only img2 should have been analyzed (img1 already had a conversation)
    mock_ai.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_pending_returns_zero_when_all_analyzed(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """When all images are already analyzed, returns total=0."""
    img = await _upload_image(client, auth_headers, test_run.id)

    conv = ImageConversation(
        image_id=uuid.UUID(img["id"]),
        messages=[{"role": "assistant", "content": "done"}],
        extracted_values={},
        status="analyzed",
    )
    db_session.add(conv)
    await db_session.flush()

    resp = await client.post(
        f"/ai/runs/{test_run.id}/analyze-pending",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["succeeded"] == 0


@pytest.mark.asyncio
async def test_analyze_pending_handles_partial_failure(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    """If one analysis fails, others still proceed."""
    await _upload_image(
        client, auth_headers, test_run.id, filename="photo1.jpg"
    )
    await _upload_image(
        client, auth_headers, test_run.id, filename="photo2.jpg"
    )

    call_count = 0

    async def _mock_with_failure(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("AI provider unavailable")
        return MOCK_ANALYSIS_RESULT

    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_with_failure),
    ):
        resp = await client.post(
            f"/ai/runs/{test_run.id}/analyze-pending",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["succeeded"] == 1
    assert data["failed"] == 1


@pytest.mark.asyncio
async def test_analyze_pending_nonexistent_run(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.post(
        f"/ai/runs/{uuid.uuid4()}/analyze-pending",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analyze_pending_on_planned_run_rejected(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    test_run.status = RunStatus.PLANNED
    await db_session.flush()

    resp = await client.post(
        f"/ai/runs/{test_run.id}/analyze-pending",
        headers=auth_headers,
    )
    assert resp.status_code == 409
