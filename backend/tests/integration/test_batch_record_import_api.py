"""Integration tests for batch record import API endpoints."""

import io
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batch_record_import import (
    BatchRecordImport,
    BatchRecordImportStatus,
)
from app.models.execution import AuditLog
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.jobs import BackgroundJob, JobStatus
from app.models.science import Project, Protocol, Run
from app.services.core.background_jobs import BackgroundJobService
from fastapi import HTTPException
from app.services.batch.batch_record_extractor import (
    BatchRecordExtraction,
    StepMapping,
    ParamMapping,
)


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _load_fixture_extraction() -> dict:
    return json.loads(
        (FIXTURES_DIR / "sample_batch_record_extraction.json").read_text()
    )


def _load_fixture_pdf() -> bytes:
    return (FIXTURES_DIR / "sample_batch_record.pdf").read_bytes()


# ── Autouse mock: prevent real background extraction ─────────────────


@pytest.fixture(autouse=True)
def mock_task_runner():
    """No-op the TaskRunner.submit so background extraction doesn't fire."""
    with patch(
        "app.api.endpoints.batch_record_import.get_task_runner",
    ) as mock_get:
        mock_runner = MagicMock()
        mock_runner.submit = MagicMock()
        mock_get.return_value = mock_runner
        yield mock_runner


@pytest.fixture(autouse=True)
def mock_file_storage():
    """Mock FileStorageService to avoid disk I/O."""
    stored = MagicMock()
    stored.original_filename = "test_batch_record.pdf"
    stored.mime_type = "application/pdf"
    stored.relative_path = "batch-imports/test/fake.pdf"
    stored.size_bytes = 1024

    with patch(
        "app.api.endpoints.batch_record_import.FileStorageService",
    ) as mock_cls:
        instance = MagicMock()
        instance.store_file = AsyncMock(return_value=stored)
        mock_cls.return_value = instance
        yield instance


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def protocol(
    db_session: AsyncSession, test_project: Project, test_org: Organization,
) -> Protocol:
    """Create a protocol with a graph containing 3 unitOp nodes."""
    p = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="PUBLISHED",
        graph={
            "nodes": [
                {
                    "id": "node-buf",
                    "type": "unitOp",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "label": "Buffer Preparation",
                        "paramSchema": {
                            "type": "object",
                            "properties": {
                                "ph_value": {"type": "number", "title": "pH Value"},
                                "temperature_c": {"type": "number", "title": "Temperature (°C)"},
                                "volume_ml": {"type": "number", "title": "Volume (mL)"},
                            },
                        },
                    },
                },
                {
                    "id": "node-cent",
                    "type": "unitOp",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "label": "Centrifugation",
                        "paramSchema": {
                            "type": "object",
                            "properties": {
                                "speed_g": {"type": "number", "title": "Speed (g)"},
                                "duration_min": {"type": "number", "title": "Duration (min)"},
                                "temp_c": {"type": "number", "title": "Temperature (°C)"},
                            },
                        },
                    },
                },
                {
                    "id": "node-filter",
                    "type": "unitOp",
                    "position": {"x": 400, "y": 0},
                    "data": {
                        "label": "Filtration",
                        "paramSchema": {
                            "type": "object",
                            "properties": {
                                "filter_size_um": {"type": "number", "title": "Filter Size (μm)"},
                            },
                        },
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "node-buf", "target": "node-cent"},
                {"id": "e2", "source": "node-cent", "target": "node-filter"},
            ],
        },
    )
    db_session.add(p)
    await db_session.flush()
    return p


@pytest_asyncio.fixture
async def import_in_review(
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
    protocol: Protocol,
) -> BatchRecordImport:
    """Create a BatchRecordImport in REVIEW status with extraction data."""
    extraction = _load_fixture_extraction()
    extraction["step_mappings"] = [
        {
            "extracted_step_index": 0,
            "extracted_step_name": "Buffer Preparation",
            "protocol_step_id": "node-buf",
            "protocol_step_name": "Buffer Preparation",
            "score": 0.92,
            "param_mappings": [
                {
                    "extracted_param_index": 0,
                    "extracted_label": "pH",
                    "extracted_value": 7.2,
                    "extracted_unit": None,
                    "schema_field_key": "ph_value",
                    "schema_field_label": "pH Value",
                    "confidence": 0.95,
                },
                {
                    "extracted_param_index": 1,
                    "extracted_label": "Temperature",
                    "extracted_value": 25.0,
                    "extracted_unit": "°C",
                    "schema_field_key": "temperature_c",
                    "schema_field_label": "Temperature (°C)",
                    "confidence": 0.93,
                },
            ],
        },
        {
            "extracted_step_index": 1,
            "extracted_step_name": "Centrifugation",
            "protocol_step_id": "node-cent",
            "protocol_step_name": "Centrifugation",
            "score": 0.88,
            "param_mappings": [
                {
                    "extracted_param_index": 0,
                    "extracted_label": "Speed",
                    "extracted_value": 3000,
                    "extracted_unit": "g",
                    "schema_field_key": "speed_g",
                    "schema_field_label": "Speed (g)",
                    "confidence": 0.94,
                },
            ],
        },
        # NOTE: no mapping for extraction step index 2 ("Mystery Step")
        # and no mapping for protocol node "node-filter" — both are unmatched
    ]

    row = BatchRecordImport(
        org_id=test_org.id,
        project_id=test_project.id,
        uploaded_by_id=test_user.id,
        status=BatchRecordImportStatus.REVIEW.value,
        original_filename="batch_record.pdf",
        mime_type="application/pdf",
        file_path="batch-imports/test/batch_record.pdf",
        file_size_bytes=2048,
        page_count=2,
        protocol_id=protocol.id,
        extraction_result=extraction,
    )
    db_session.add(row)
    await db_session.flush()
    return row


# ── Upload endpoint tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_returns_extracting(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    protocol: Protocol,
):
    resp = await client.post(
        "/science/batch-record-imports",
        files={"file": ("batch.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        data={"project_id": str(test_project.id), "protocol_id": str(protocol.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "EXTRACTING"
    assert body["import_id"] is not None
    assert body["protocol_id"] == str(protocol.id)


@pytest.mark.asyncio
async def test_upload_invalid_file_type(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    protocol: Protocol,
    mock_file_storage,
):
    from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY

    mock_file_storage.store_file = AsyncMock(
        side_effect=HTTPException(422, "Unsupported file type"),
    )

    resp = await client.post(
        "/science/batch-record-imports",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"project_id": str(test_project.id), "protocol_id": str(protocol.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_no_permission(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    protocol: Protocol,
):
    resp = await client.post(
        "/science/batch-record-imports",
        files={"file": ("batch.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        data={"project_id": str(test_project.id), "protocol_id": str(protocol.id)},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_upload_archived_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
    test_org: Organization,
):
    archived = Protocol(
        name="Archived Proto",
        project_id=test_project.id,
        status="ARCHIVED",
        graph={},
    )
    db_session.add(archived)
    await db_session.flush()

    resp = await client.post(
        "/science/batch-record-imports",
        files={"file": ("batch.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        data={"project_id": str(test_project.id), "protocol_id": str(archived.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ── GET endpoint tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_progress_while_extracting(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
    protocol: Protocol,
):
    # Create import in EXTRACTING status
    row = BatchRecordImport(
        org_id=test_org.id,
        project_id=test_project.id,
        uploaded_by_id=test_user.id,
        status=BatchRecordImportStatus.EXTRACTING.value,
        original_filename="batch.pdf",
        mime_type="application/pdf",
        file_path="batch-imports/test/batch.pdf",
        file_size_bytes=1024,
        protocol_id=protocol.id,
    )
    db_session.add(row)
    await db_session.flush()

    # Create a BackgroundJob with progress
    job = await BackgroundJobService.create(
        db_session, "batch_record_extract", "batch_record_import", row.id,
    )
    await db_session.flush()
    await BackgroundJobService.update_progress(
        db_session, job, "extracting", "Extracting page 3 of 12", 3, 12,
    )

    resp = await client.get(
        f"/science/batch-record-imports/{row.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXTRACTING"
    assert body["progress"] is not None
    assert body["progress"]["stage"] == "extracting"
    assert body["progress"]["current"] == 3
    assert body["progress"]["total"] == 12


@pytest.mark.asyncio
async def test_get_extraction_when_review(
    client: AsyncClient,
    auth_headers: dict,
    import_in_review: BatchRecordImport,
):
    resp = await client.get(
        f"/science/batch-record-imports/{import_in_review.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "REVIEW"
    assert body["extraction"] is not None
    assert len(body["extraction"]["steps"]) == 2
    assert body["extraction"]["steps"][0]["step_name"] == "Buffer Preparation"
    # 2 steps mapped out of 2 extracted
    assert len(body["step_mappings"]) == 2
    assert body["step_mappings"][0]["protocol_step_id"] == "node-buf"
    assert body["step_mappings"][0]["score"] == 0.92


@pytest.mark.asyncio
async def test_get_returns_run_id_when_finalized(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
    protocol: Protocol,
):
    # Create a real Run so FK is satisfied
    run = Run(
        name="Finalized Run",
        project_id=test_project.id,
        protocol_id=protocol.id,
        status="COMPLETED",
        graph=protocol.graph,
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()

    row = BatchRecordImport(
        org_id=test_org.id,
        project_id=test_project.id,
        uploaded_by_id=test_user.id,
        status=BatchRecordImportStatus.FINALIZED.value,
        original_filename="done.pdf",
        mime_type="application/pdf",
        file_path="batch-imports/test/done.pdf",
        file_size_bytes=512,
        protocol_id=protocol.id,
        created_run_id=run.id,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.get(
        f"/science/batch-record-imports/{row.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "FINALIZED"
    assert resp.json()["created_run_id"] == str(run.id)


@pytest.mark.asyncio
async def test_get_returns_error_when_failed(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
    protocol: Protocol,
):
    row = BatchRecordImport(
        org_id=test_org.id,
        project_id=test_project.id,
        uploaded_by_id=test_user.id,
        status=BatchRecordImportStatus.FAILED.value,
        original_filename="bad.pdf",
        mime_type="application/pdf",
        file_path="batch-imports/test/bad.pdf",
        file_size_bytes=256,
        protocol_id=protocol.id,
        error_message="Vision model timeout",
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.get(
        f"/science/batch-record-imports/{row.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "FAILED"
    assert resp.json()["error_message"] == "Vision model timeout"


@pytest.mark.asyncio
async def test_get_nonexistent_import(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.get(
        f"/science/batch-record-imports/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── Finalize endpoint tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_creates_completed_run(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    import_in_review: BatchRecordImport,
    protocol: Protocol,
):
    resp = await client.post(
        f"/science/batch-record-imports/{import_in_review.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "Imported Run LOT-042",
            "step_mappings": [
                {
                    "protocol_step_id": "node-buf",
                    "values": [
                        {
                            "schema_field_key": "ph_value",
                            "value": 7.2,
                            "accepted": True,
                            "edited": False,
                            "original_value": 7.2,
                            "original_confidence": 0.95,
                        },
                        {
                            "schema_field_key": "temperature_c",
                            "value": 25.0,
                            "accepted": True,
                            "edited": False,
                            "original_value": 25.0,
                            "original_confidence": 0.93,
                        },
                    ],
                },
                {
                    "protocol_step_id": "node-cent",
                    "values": [
                        {
                            "schema_field_key": "speed_g",
                            "value": 3000,
                            "accepted": True,
                            "edited": False,
                            "original_value": 3000,
                            "original_confidence": 0.94,
                        },
                    ],
                },
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["run_name"] == "Imported Run LOT-042"
    assert body["run_id"] is not None

    # Verify Run in DB
    run = await db_session.get(Run, uuid.UUID(body["run_id"]))
    assert run is not None
    assert run.status == "COMPLETED"
    assert run.execution_data["node-buf"]["status"] == "completed"
    assert run.execution_data["node-buf"]["results"]["ph_value"] == 7.2
    assert run.execution_data["node-cent"]["results"]["speed_g"] == 3000
    assert run.graph is not None
    assert len(run.graph.get("nodes", [])) == 3


@pytest.mark.asyncio
async def test_finalize_with_user_resolved_mapping(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    import_in_review: BatchRecordImport,
    protocol: Protocol,
):
    """User manually assigned an extracted value to node-filter."""
    resp = await client.post(
        f"/science/batch-record-imports/{import_in_review.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "User Resolved Run",
            "step_mappings": [
                {
                    "protocol_step_id": "node-buf",
                    "values": [
                        {"schema_field_key": "ph_value", "value": 7.2,
                         "accepted": True, "original_confidence": 0.95},
                    ],
                },
                {
                    "protocol_step_id": "node-cent",
                    "values": [
                        {"schema_field_key": "speed_g", "value": 3000,
                         "accepted": True, "original_confidence": 0.94},
                    ],
                },
                {
                    "protocol_step_id": "node-filter",
                    "values": [
                        {"schema_field_key": "filter_size_um", "value": 0.22,
                         "accepted": True, "original_confidence": 0.0},
                    ],
                },
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    run = await db_session.get(Run, uuid.UUID(resp.json()["run_id"]))
    assert run.execution_data["node-filter"]["status"] == "completed"
    assert run.execution_data["node-filter"]["results"]["filter_size_um"] == 0.22


@pytest.mark.asyncio
async def test_finalize_with_na_step(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    import_in_review: BatchRecordImport,
    protocol: Protocol,
):
    resp = await client.post(
        f"/science/batch-record-imports/{import_in_review.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "NA Step Run",
            "step_mappings": [
                {
                    "protocol_step_id": "node-buf",
                    "values": [
                        {"schema_field_key": "ph_value", "value": 7.2,
                         "accepted": True, "original_confidence": 0.95},
                    ],
                },
                {
                    "protocol_step_id": "node-cent",
                    "na": True,
                    "na_reason": "Run ended early — batch failed QC",
                },
                {
                    "protocol_step_id": "node-filter",
                    "na": True,
                    "na_reason": "Not performed",
                },
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    run = await db_session.get(Run, uuid.UUID(resp.json()["run_id"]))
    assert run.execution_data["node-cent"]["status"] == "na"
    assert "batch failed QC" in run.execution_data["node-cent"]["na_reason"]
    assert run.execution_data["node-filter"]["status"] == "na"


@pytest.mark.asyncio
async def test_finalize_links_source_document(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    import_in_review: BatchRecordImport,
    protocol: Protocol,
):
    resp = await client.post(
        f"/science/batch-record-imports/{import_in_review.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "Attachment Run",
            "step_mappings": [
                {
                    "protocol_step_id": "node-buf",
                    "values": [
                        {"schema_field_key": "ph_value", "value": 7.2,
                         "accepted": True, "original_confidence": 0.95},
                    ],
                },
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    run = await db_session.get(Run, uuid.UUID(resp.json()["run_id"]))
    assert len(run.attachments) == 1
    att = run.attachments[0]
    assert att["filename"] == "batch_record.pdf"
    assert att["content_type"] == "application/pdf"
    assert att["file_path"] == import_in_review.file_path
    assert att["deleted"] is False


@pytest.mark.asyncio
async def test_finalize_creates_audit_log(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    import_in_review: BatchRecordImport,
    protocol: Protocol,
    test_user: User,
):
    resp = await client.post(
        f"/science/batch-record-imports/{import_in_review.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "Audit Run",
            "step_mappings": [
                {
                    "protocol_step_id": "node-buf",
                    "values": [
                        {"schema_field_key": "ph_value", "value": 7.2,
                         "accepted": True, "original_confidence": 0.95},
                        {"schema_field_key": "temperature_c", "value": 26.0,
                         "accepted": True, "edited": True,
                         "original_value": 25.0, "original_confidence": 0.93},
                    ],
                },
                {
                    "protocol_step_id": "node-cent",
                    "values": [
                        {"schema_field_key": "speed_g", "value": 3000,
                         "accepted": False, "original_confidence": 0.4},
                    ],
                },
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run_id = uuid.UUID(resp.json()["run_id"])

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "Run",
            AuditLog.entity_id == run_id,
            AuditLog.action == "IMPORT",
        )
    )
    audit = result.scalar_one()
    assert audit.actor_id == test_user.id
    assert audit.changes["source"] == "batch_record_import"
    assert audit.changes["source_document"] == "batch_record.pdf"
    assert audit.changes["values_accepted"] == 2
    assert audit.changes["values_rejected"] == 1
    assert audit.changes["values_edited"] == 1


@pytest.mark.asyncio
async def test_finalize_with_edited_values(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    import_in_review: BatchRecordImport,
    protocol: Protocol,
):
    """User edited a value — original preserved in reviewed_data."""
    resp = await client.post(
        f"/science/batch-record-imports/{import_in_review.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "Edited Values Run",
            "step_mappings": [
                {
                    "protocol_step_id": "node-buf",
                    "values": [
                        {
                            "schema_field_key": "ph_value",
                            "value": 7.4,
                            "accepted": True,
                            "edited": True,
                            "original_value": 7.2,
                            "original_confidence": 0.95,
                        },
                    ],
                },
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # Verify the run has the edited value
    run = await db_session.get(Run, uuid.UUID(resp.json()["run_id"]))
    assert run.execution_data["node-buf"]["results"]["ph_value"] == 7.4

    # Verify reviewed_data preserves the edit audit trail
    await db_session.refresh(import_in_review)
    reviewed = import_in_review.reviewed_data
    assert reviewed is not None
    val = reviewed["step_mappings"][0]["values"][0]
    assert val["edited"] is True
    assert val["original_value"] == 7.2
    assert val["value"] == 7.4


@pytest.mark.asyncio
async def test_finalize_rejects_already_finalized(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
    protocol: Protocol,
):
    # Create a real Run so FK is satisfied
    run = Run(
        name="Already Done",
        project_id=test_project.id,
        protocol_id=protocol.id,
        status="COMPLETED",
        graph={},
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()

    row = BatchRecordImport(
        org_id=test_org.id,
        project_id=test_project.id,
        uploaded_by_id=test_user.id,
        status=BatchRecordImportStatus.FINALIZED.value,
        original_filename="done.pdf",
        mime_type="application/pdf",
        file_path="batch-imports/test/done.pdf",
        file_size_bytes=512,
        protocol_id=protocol.id,
        created_run_id=run.id,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.post(
        f"/science/batch-record-imports/{row.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "Should Fail",
            "step_mappings": [],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_finalize_preserves_timestamps_signatures_deviations(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    import_in_review: BatchRecordImport,
    protocol: Protocol,
):
    """Finalize carries timestamps/signatures/deviations into Run.execution_data."""
    resp = await client.post(
        f"/science/batch-record-imports/{import_in_review.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "Timestamped Run",
            "step_mappings": [
                {
                    "protocol_step_id": "node-buf",
                    "values": [
                        {
                            "schema_field_key": "ph_value",
                            "value": 7.2,
                            "accepted": True,
                            "original_confidence": 0.95,
                        },
                    ],
                    "notes": "ok",
                    "na": False,
                    "na_reason": "",
                    "timestamps": [
                        {
                            "label": "Start Time",
                            "value": "08:30",
                            "confidence": 0.9,
                        },
                    ],
                    "signatures": [
                        {
                            "initials_or_name": "JKL",
                            "role": "Operator",
                            "confidence": 0.88,
                        },
                    ],
                    "deviations": [
                        {
                            "description": "Minor delay",
                            "severity": "minor",
                            "step_reference": "",
                            "confidence": 0.7,
                        },
                    ],
                },
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    run = await db_session.get(Run, uuid.UUID(resp.json()["run_id"]))
    step_data = run.execution_data["node-buf"]

    assert step_data["status"] == "completed"

    assert len(step_data["timestamps"]) == 1
    assert step_data["timestamps"][0]["label"] == "Start Time"
    assert step_data["timestamps"][0]["value"] == "08:30"
    assert step_data["timestamps"][0]["confidence"] == 0.9

    assert len(step_data["signatures"]) == 1
    assert step_data["signatures"][0]["initials_or_name"] == "JKL"
    assert step_data["signatures"][0]["role"] == "Operator"
    assert step_data["signatures"][0]["confidence"] == 0.88

    assert len(step_data["deviations"]) == 1
    assert step_data["deviations"][0]["description"] == "Minor delay"
    assert step_data["deviations"][0]["severity"] == "minor"
    assert step_data["deviations"][0]["confidence"] == 0.7


@pytest.mark.asyncio
async def test_finalize_rejects_extracting_status(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
    protocol: Protocol,
):
    row = BatchRecordImport(
        org_id=test_org.id,
        project_id=test_project.id,
        uploaded_by_id=test_user.id,
        status=BatchRecordImportStatus.EXTRACTING.value,
        original_filename="still_processing.pdf",
        mime_type="application/pdf",
        file_path="batch-imports/test/still.pdf",
        file_size_bytes=512,
        protocol_id=protocol.id,
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.post(
        f"/science/batch-record-imports/{row.id}/finalize",
        json={
            "protocol_id": str(protocol.id),
            "run_name": "Should Fail",
            "step_mappings": [],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409
