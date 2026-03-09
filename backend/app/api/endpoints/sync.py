"""Offline sync queue processor: batch-processes queued offline actions."""

import base64
import uuid
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user_or_offline, get_db
from app.models.ai import RunImage, ImageConversation
from app.models.iam import User
from app.models.science import Run
from app.schemas.offline import (
    SyncAction,
    SyncActionResult,
    SyncQueueRequest,
    SyncQueueResponse,
)
from app.services.audit import log_audit

router = APIRouter()

# Tolerance for numeric value comparison (5%)
VALUE_TOLERANCE_PERCENT = 5.0


def values_match(manual, ai, tolerance_pct: float = VALUE_TOLERANCE_PERCENT) -> bool:
    """Compare manual and AI values with tolerance for numerics."""
    if manual is None or ai is None:
        return manual == ai
    # Try numeric comparison
    try:
        m = float(manual)
        a = float(ai)
        if a == 0:
            return m == 0
        return abs(m - a) / abs(a) * 100 <= tolerance_pct
    except (TypeError, ValueError):
        # String comparison (exact match)
        return str(manual).strip().lower() == str(ai).strip().lower()


@router.post("/sync/offline-queue/{run_id}", response_model=SyncQueueResponse)
async def process_offline_queue(
    run_id: UUID,
    body: SyncQueueRequest,
    auth: tuple[User, dict | None] = Depends(get_current_user_or_offline),
    db: AsyncSession = Depends(get_db),
):
    """Process a batch of queued offline actions for a run.

    Accepts both normal and offline tokens. For offline tokens,
    validates the token is scoped to the requested run.
    """
    user, offline_payload = auth

    # If using offline token, verify it's scoped to this run
    if offline_payload is not None:
        token_run_id = offline_payload.get("run_id")
        if token_run_id != str(run_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Offline token is not scoped to this run",
            )

    # Verify run exists
    run_result = await db.execute(select(Run).where(Run.id == run_id))
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    results: list[SyncActionResult] = []
    succeeded = 0
    failed = 0

    for idx, action in enumerate(body.actions):
        try:
            result = await _process_action(db, run, user, action, idx)
            results.append(result)
            if result.success:
                succeeded += 1
            else:
                failed += 1
        except Exception as e:
            results.append(
                SyncActionResult(
                    index=idx,
                    action_type=action.action_type,
                    success=False,
                    error=str(e),
                )
            )
            failed += 1

    await db.commit()

    return SyncQueueResponse(
        total=len(body.actions),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


async def _process_action(
    db: AsyncSession,
    run: Run,
    user: User,
    action: SyncAction,
    index: int,
) -> SyncActionResult:
    """Process a single sync action."""
    if action.action_type == "image_upload":
        return await _handle_image_upload(db, run, user, action, index)
    elif action.action_type == "parameter_tag":
        return await _handle_parameter_tag(db, action, index)
    elif action.action_type == "manual_values":
        return await _handle_manual_values(db, run, user, action, index)
    else:
        return SyncActionResult(
            index=index,
            action_type=action.action_type,
            success=False,
            error=f"Unknown action type: {action.action_type}",
        )


async def _handle_image_upload(
    db: AsyncSession,
    run: Run,
    user: User,
    action: SyncAction,
    index: int,
) -> SyncActionResult:
    """Save a base64-encoded image to disk and create RunImage record."""
    if not action.image_data:
        return SyncActionResult(
            index=index, action_type="image_upload", success=False,
            error="Missing image_data",
        )
    if not action.step_id:
        return SyncActionResult(
            index=index, action_type="image_upload", success=False,
            error="Missing step_id",
        )

    # Decode base64
    try:
        image_bytes = base64.b64decode(action.image_data)
    except Exception:
        return SyncActionResult(
            index=index, action_type="image_upload", success=False,
            error="Invalid base64 image data",
        )

    # Save to disk
    filename = action.image_filename or f"offline_{uuid.uuid4().hex[:8]}.jpg"
    upload_dir = Path(settings.image_storage_path) / str(run.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    file_path.write_bytes(image_bytes)

    # Create RunImage record
    image = RunImage(
        run_id=run.id,
        step_id=action.step_id,
        file_path=str(file_path.relative_to(Path(settings.image_storage_path))),
        original_filename=filename,
        mime_type="image/png" if filename.endswith(".png") else "image/jpeg",
        file_size_bytes=len(image_bytes),
        uploaded_by_id=user.id,
        parameter_tags=action.parameter_tags,
    )
    db.add(image)
    await db.flush()

    return SyncActionResult(
        index=index, action_type="image_upload", success=True,
        image_id=image.id,
    )


async def _handle_parameter_tag(
    db: AsyncSession,
    action: SyncAction,
    index: int,
) -> SyncActionResult:
    """Update parameter tags on an existing image."""
    if not action.image_id:
        return SyncActionResult(
            index=index, action_type="parameter_tag", success=False,
            error="Missing image_id",
        )

    result = await db.execute(
        select(RunImage).where(RunImage.id == action.image_id)
    )
    image = result.scalar_one_or_none()
    if image is None:
        return SyncActionResult(
            index=index, action_type="parameter_tag", success=False,
            error="Image not found",
        )

    image.parameter_tags = action.parameter_tags
    await db.flush()

    return SyncActionResult(
        index=index, action_type="parameter_tag", success=True,
        image_id=image.id,
    )


async def _handle_manual_values(
    db: AsyncSession,
    run: Run,
    user: User,
    action: SyncAction,
    index: int,
) -> SyncActionResult:
    """Store manual values for a step. Flags discrepancies if AI values exist."""
    if not action.step_id or not action.values:
        return SyncActionResult(
            index=index, action_type="manual_values", success=False,
            error="Missing step_id or values",
        )

    execution_data = dict(run.execution_data or {})
    step_data = dict(execution_data.get(action.step_id, {}))

    # Store manual values
    existing_results = dict(step_data.get("results", {}))
    manual_results = dict(step_data.get("manual_results", {}))

    discrepancies = []
    for key, manual_val in action.values.items():
        manual_results[key] = manual_val

        # Check against existing AI-confirmed values
        ai_val = existing_results.get(key)
        if ai_val is not None and not values_match(manual_val, ai_val):
            discrepancies.append({
                "field": key,
                "manual": manual_val,
                "ai": ai_val,
            })

    step_data["manual_results"] = manual_results
    step_data["offline_sync_user_id"] = str(user.id)
    execution_data[action.step_id] = step_data
    run.execution_data = execution_data

    # Log discrepancies for notification later
    if discrepancies:
        step_data["value_discrepancies"] = discrepancies

    await db.flush()

    return SyncActionResult(
        index=index, action_type="manual_values", success=True,
    )
