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
        slug="signoff-service-test-run",
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def sample_user_with_signature(test_user: User, tmp_path) -> User:
    """A user whose ``signature_full_path`` is a storage-root-relative path.

    Mirrors production: ``auth.upload_signature`` stores the signature path
    relative to the ``FileStorageService`` storage root (e.g.
    ``{org_id}/signatures/{user_id}-drawn.png``), not an absolute filesystem
    path.  Tests monkeypatch the storage root to ``tmp_path / "uploads"`` so
    this relative path resolves there.
    """
    relative = f"{test_user.id}/signatures/{test_user.id}-drawn.png"
    sig = tmp_path / "uploads" / relative
    sig.parent.mkdir(parents=True, exist_ok=True)
    sig.write_bytes(b"\x89PNG\r\n\x1a\n")
    test_user.signature_full_path = relative
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


async def test_create_run_signoff_resolves_relative_signature_path(
    db_session: AsyncSession,
    sample_run: Run,
    test_user: User,
    tmp_path,
    monkeypatch,
):
    """A signer's signature_full_path is stored RELATIVE to the storage root
    (``{org_id}/signatures/{user_id}-full.png``) — the shape the
    ``/auth/me/signature`` upload writes. ``create_signoff`` must resolve it
    against the storage root before copying, otherwise ``shutil.copyfile``
    opens the relative path against the process CWD and raises
    ``FileNotFoundError``, surfacing as an unhandled 500 on every APPROVED
    sign-off (F-0080: the async review queue can never complete a sign-off).
    """
    storage_root = tmp_path / "uploads"
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", storage_root) or None,
    )

    # Write the source signature file at a RELATIVE path under the storage
    # root, exactly as the signature-upload endpoint does in production.
    relative_sig = "test-org/signatures/test-user-full.png"
    src_abs = storage_root / relative_sig
    src_abs.parent.mkdir(parents=True, exist_ok=True)
    src_abs.write_bytes(b"\x89PNG\r\n\x1a\n")
    test_user.signature_full_path = relative_sig

    signoff = await create_signoff(
        db_session,
        entity_type="run",
        entity_id=sample_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer=test_user,
        attestation="I performed this run...",
        signoff_request_id=None,
    )

    assert signoff.signature_image_path is not None
    # The record-scoped copy was actually written under the storage root.
    copied = storage_root / signoff.signature_image_path
    assert copied.exists()
    assert copied.read_bytes() == b"\x89PNG\r\n\x1a\n"


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


async def test_create_signoff_commit_false_defers_commit(
    db_session: AsyncSession,
    sample_run: Run,
    sample_user_with_signature: User,
    tmp_path,
    monkeypatch,
):
    """commit=False flushes the row but does not commit, so the caller can
    keep the transaction open — the run sign-off and its request fulfillment
    must land in a single commit (F-0080 atomicity)."""
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", tmp_path / "uploads") or None,
    )
    commits: list[int] = []
    original_commit = db_session.commit

    async def _counting_commit() -> None:
        commits.append(1)
        await original_commit()

    monkeypatch.setattr(db_session, "commit", _counting_commit)

    signoff = await create_signoff(
        db_session,
        entity_type="run",
        entity_id=sample_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer=sample_user_with_signature,
        attestation="I performed this run...",
        signoff_request_id=None,
        commit=False,
    )

    assert commits == []  # create_signoff did not commit
    assert signoff.id is not None  # but the row was flushed


async def test_create_signoff_commit_true_commits(
    db_session: AsyncSession,
    sample_run: Run,
    sample_user_with_signature: User,
    tmp_path,
    monkeypatch,
):
    """The default (commit=True) still commits exactly once — the protocol
    sign-off path relies on create_signoff owning the commit."""
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", tmp_path / "uploads") or None,
    )
    commits: list[int] = []
    original_commit = db_session.commit

    async def _counting_commit() -> None:
        commits.append(1)
        await original_commit()

    monkeypatch.setattr(db_session, "commit", _counting_commit)

    await create_signoff(
        db_session,
        entity_type="run",
        entity_id=sample_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer=sample_user_with_signature,
        attestation="I performed this run...",
        signoff_request_id=None,
    )

    assert commits == [1]
