import uuid
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import RunImage, ImageConversation
from app.models.execution import AuditLog
from app.models.science import Project, Protocol, Run, RunStatus
from app.models.iam import User
from app.services.ai_vision import ImageAnalysisResult, ExtractedValue


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

MOCK_ANALYSIS_RESULT = ImageAnalysisResult(
    message="I can see a cell counting display. Viable Cell Density: 2.4×10⁶ cells/mL, Viability: 96.2%.",
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

MOCK_CLARIFICATION_RESULT = ImageAnalysisResult(
    message="I see a value of 2.4M but I'm not sure which field it belongs to. Is this the viable cell density?",
    extracted_values=[
        ExtractedValue(
            field_key="viable_cell_density",
            field_label="Viable Cell Density",
            value=2400000.0,
            unit="cells/mL",
            confidence=0.4,
        ),
    ],
    needs_clarification=True,
)

MOCK_CONFIRMED_RESULT = ImageAnalysisResult(
    message="Confirmed. Viable Cell Density is 2.4×10⁶ cells/mL.",
    extracted_values=[
        ExtractedValue(
            field_key="viable_cell_density",
            field_label="Viable Cell Density",
            value=2400000.0,
            unit="cells/mL",
            confidence=0.98,
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


@pytest_asyncio.fixture
async def uploaded_image(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
) -> dict:
    """Upload an image and return the response data."""
    resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("photo.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()


def _mock_analyze(*args, **kwargs):
    return MOCK_ANALYSIS_RESULT


def _mock_analyze_clarify(*args, **kwargs):
    return MOCK_CLARIFICATION_RESULT


def _mock_converse(*args, **kwargs):
    return MOCK_CONFIRMED_RESULT


# ── Analyze Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_returns_extracted_values(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
):
    image_id = uploaded_image["id"]

    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze),
    ):
        resp = await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_clarification"] is False
    assert len(data["extracted_values"]) == 2
    assert data["extracted_values"][0]["field_key"] == "viable_cell_density"
    assert data["extracted_values"][0]["value"] == 2400000.0
    assert data["extracted_values"][1]["field_key"] == "viability_percent"
    assert data["message"] is not None


@pytest.mark.asyncio
async def test_analyze_creates_conversation(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
    db_session: AsyncSession,
):
    image_id = uploaded_image["id"]

    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze),
    ):
        resp = await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    conv_data = resp.json()["conversation"]
    assert conv_data["status"] == "analyzed"
    assert len(conv_data["messages"]) == 1
    assert conv_data["messages"][0]["role"] == "assistant"

    # Verify in DB
    result = await db_session.execute(
        select(ImageConversation).where(
            ImageConversation.image_id == uuid.UUID(image_id)
        )
    )
    conv = result.scalar_one()
    assert conv.status == "analyzed"


@pytest.mark.asyncio
async def test_analyze_with_clarification(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
):
    image_id = uploaded_image["id"]

    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze_clarify),
    ):
        resp = await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_clarification"] is True
    assert data["conversation"]["status"] == "needs_clarification"


@pytest.mark.asyncio
async def test_analyze_nonexistent_image(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
):
    resp = await client.post(
        f"/ai/runs/{test_run.id}/images/{uuid.uuid4()}/analyze",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analyze_planned_run_rejected(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
    db_session: AsyncSession,
):
    test_run.status = RunStatus.PLANNED
    await db_session.flush()

    resp = await client.post(
        f"/ai/runs/{test_run.id}/images/{uploaded_image['id']}/analyze",
        headers=auth_headers,
    )
    assert resp.status_code == 409


# ── Converse Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_converse_appends_messages(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
):
    image_id = uploaded_image["id"]

    # First: analyze
    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze_clarify),
    ):
        await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )

    # Then: converse
    with patch(
        "app.api.endpoints.ai.continue_conversation",
        new_callable=lambda: AsyncMock(side_effect=_mock_converse),
    ):
        resp = await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/converse",
            json={"message": "Yes, that's the viable cell density"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_clarification"] is False
    # Conversation should have: assistant (analyze) + user + assistant (converse)
    messages = data["conversation"]["messages"]
    assert len(messages) == 3
    assert messages[0]["role"] == "assistant"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Yes, that's the viable cell density"
    assert messages[2]["role"] == "assistant"


@pytest.mark.asyncio
async def test_converse_without_analyze_returns_404(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
):
    resp = await client.post(
        f"/ai/runs/{test_run.id}/images/{uploaded_image['id']}/converse",
        json={"message": "test"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert "Call /analyze first" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_converse_updates_extracted_values(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
    db_session: AsyncSession,
):
    image_id = uploaded_image["id"]

    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze_clarify),
    ):
        await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )

    with patch(
        "app.api.endpoints.ai.continue_conversation",
        new_callable=lambda: AsyncMock(side_effect=_mock_converse),
    ):
        resp = await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/converse",
            json={"message": "Yes"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    conv = resp.json()["conversation"]
    assert conv["status"] == "analyzed"
    assert "viable_cell_density" in conv["extracted_values"]


# ── Confirm Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_writes_to_execution_data(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
    db_session: AsyncSession,
):
    image_id = uploaded_image["id"]

    # Analyze first
    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze),
    ):
        await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )

    # Confirm values
    resp = await client.post(
        f"/ai/runs/{test_run.id}/images/{image_id}/confirm",
        json={
            "values": {
                "viable_cell_density": 2400000.0,
                "viability_percent": 96.2,
            }
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_data_updated"] is True
    assert data["conversation"]["status"] == "confirmed"

    # Verify execution_data on the run
    await db_session.refresh(test_run)
    step_data = test_run.execution_data.get("step-1", {})
    results = step_data.get("results", {})
    assert results["viable_cell_density"] == 2400000.0
    assert results["viability_percent"] == 96.2


@pytest.mark.asyncio
async def test_confirm_creates_audit_log(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    test_user: User,
    uploaded_image: dict,
    db_session: AsyncSession,
):
    image_id = uploaded_image["id"]

    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze),
    ):
        await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )

    await client.post(
        f"/ai/runs/{test_run.id}/images/{image_id}/confirm",
        json={"values": {"viable_cell_density": 2400000.0}},
        headers=auth_headers,
    )

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "Run",
            AuditLog.entity_id == test_run.id,
            AuditLog.action == "IMAGE_CONFIRM",
        )
    )
    audit = result.scalar_one_or_none()
    assert audit is not None
    assert audit.changes["image_id"] == image_id
    assert audit.changes["step_id"] == "step-1"
    assert "viable_cell_density" in audit.changes["confirmed_values"]


@pytest.mark.asyncio
async def test_confirm_empty_values_rejected(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
    db_session: AsyncSession,
):
    image_id = uploaded_image["id"]

    # Create a conversation
    conv = ImageConversation(
        image_id=uuid.UUID(image_id),
        messages=[{"role": "assistant", "content": "test"}],
        extracted_values={},
        status="analyzed",
    )
    db_session.add(conv)
    await db_session.flush()

    resp = await client.post(
        f"/ai/runs/{test_run.id}/images/{image_id}/confirm",
        json={"values": {}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_confirm_without_conversation_returns_404(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
):
    resp = await client.post(
        f"/ai/runs/{test_run.id}/images/{uploaded_image['id']}/confirm",
        json={"values": {"viable_cell_density": 100.0}},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_confirm_preserves_existing_execution_data(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    uploaded_image: dict,
    db_session: AsyncSession,
):
    image_id = uploaded_image["id"]

    # Pre-populate some execution data
    test_run.execution_data = {
        "step-1": {
            "status": "in_progress",
            "results": {"some_other_field": 42},
            "notes": "existing note",
        }
    }
    await db_session.flush()

    # Analyze
    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze),
    ):
        await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )

    # Confirm
    resp = await client.post(
        f"/ai/runs/{test_run.id}/images/{image_id}/confirm",
        json={"values": {"viable_cell_density": 2400000.0}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    await db_session.refresh(test_run)
    step_data = test_run.execution_data["step-1"]
    # New value written
    assert step_data["results"]["viable_cell_density"] == 2400000.0
    # Existing data preserved
    assert step_data["results"]["some_other_field"] == 42
    assert step_data["notes"] == "existing note"


# ── Full Flow (Happy Path) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_flow_upload_analyze_converse_confirm(
    client: AsyncClient,
    auth_headers: dict,
    test_run: Run,
    tmp_image_storage: Path,
    db_session: AsyncSession,
):
    """End-to-end test: upload -> analyze -> converse -> confirm."""

    # 1. Upload
    upload_resp = await client.post(
        f"/ai/runs/{test_run.id}/steps/step-1/images",
        files={"file": ("cell_count.jpg", TINY_JPEG, "image/jpeg")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    image_id = upload_resp.json()["id"]

    # 2. Analyze (AI is uncertain)
    with patch(
        "app.api.endpoints.ai.analyze_image",
        new_callable=lambda: AsyncMock(side_effect=_mock_analyze_clarify),
    ):
        analyze_resp = await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/analyze",
            headers=auth_headers,
        )
    assert analyze_resp.status_code == 200
    assert analyze_resp.json()["needs_clarification"] is True

    # 3. Converse (user confirms)
    with patch(
        "app.api.endpoints.ai.continue_conversation",
        new_callable=lambda: AsyncMock(side_effect=_mock_converse),
    ):
        converse_resp = await client.post(
            f"/ai/runs/{test_run.id}/images/{image_id}/converse",
            json={"message": "Yes, that's the viable cell density"},
            headers=auth_headers,
        )
    assert converse_resp.status_code == 200
    assert converse_resp.json()["needs_clarification"] is False

    # 4. Confirm
    confirm_resp = await client.post(
        f"/ai/runs/{test_run.id}/images/{image_id}/confirm",
        json={"values": {"viable_cell_density": 2400000.0}},
        headers=auth_headers,
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["execution_data_updated"] is True

    # 5. Verify final state
    await db_session.refresh(test_run)
    assert test_run.execution_data["step-1"]["results"]["viable_cell_density"] == 2400000.0

    # Verify image detail shows confirmed conversation
    detail_resp = await client.get(
        f"/ai/runs/{test_run.id}/images/{image_id}",
        headers=auth_headers,
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["conversation"]["status"] == "confirmed"
