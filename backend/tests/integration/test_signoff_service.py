"""Integration tests for ``services/signoffs/service.create_signoff``.

Task 11 of F-0087 GLP Gap Fixes — single shared entry point used by both
``POST /protocols/{id}/signoffs`` and ``POST /runs/{id}/signoffs``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import AuditLog
from app.models.iam import User
from app.models.runs import Run
from app.services.core.file_storage import FileStorageService
from app.services.signoffs.service import create_signoff


@pytest_asyncio.fixture
async def sample_run(db_session: AsyncSession, test_project) -> Run:
    """A minimal PLANNED run for sign-off service tests."""
    run = Run(
        name="Signoff Service Test Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def sample_user_with_signature(test_user: User, tmp_path) -> User:
    """A user with a signature image file at signature_full_path."""
    sig = tmp_path / "sig.png"
    sig.write_bytes(b"\x89PNG\r\n\x1a\n")
    test_user.signature_full_path = str(sig)
    return test_user


async def test_create_run_signoff_copies_signature_image(
    db_session: AsyncSession,
    sample_run: Run,
    sample_user_with_signature: User,
    tmp_path,
    monkeypatch,
):
    """signature_full_path is copied to a record-scoped path at sign time so
    future re-uploads don't retroactively change past records (§11.70)."""
    # Redirect storage root into tmp_path so the copy doesn't pollute ./uploads.
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", tmp_path / "uploads") or None,
    )

    signoff = await create_signoff(
        db_session,
        entity_type="run",
        entity_id=sample_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer=sample_user_with_signature,
        attestation="I performed this run...",
        signoff_request_id=None,
    )

    assert signoff.signature_image_path is not None
    assert (
        signoff.signature_image_path != sample_user_with_signature.signature_full_path
    )
    # Record-scoped path includes the signoff id so future re-uploads to the
    # user's signature_full_path don't retroactively change past records.
    assert str(signoff.id) in signoff.signature_image_path
    # And the file was actually written under the storage root.
    full = (tmp_path / "uploads") / signoff.signature_image_path
    assert full.exists()


async def test_create_signoff_writes_audit_log(
    db_session: AsyncSession,
    sample_run: Run,
    sample_user_with_signature: User,
    tmp_path,
    monkeypatch,
):
    """create_signoff writes an AuditLog entry referencing the new sign-off."""
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", tmp_path / "uploads") or None,
    )

    signoff = await create_signoff(
        db_session,
        entity_type="run",
        entity_id=sample_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer=sample_user_with_signature,
        attestation="I performed this run...",
        signoff_request_id=None,
    )

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_id == signoff.id)
    )
    entry = result.scalar_one()
    assert entry.entity_type == "run_signoff"
    assert entry.action == "signoff.approved"
    assert entry.actor_id == sample_user_with_signature.id
