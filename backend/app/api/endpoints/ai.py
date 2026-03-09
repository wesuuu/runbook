import os
import uuid as uuid_mod
from pathlib import Path

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.ai import (
    AiProviderConfig,
    ImageConversation,
    RunImage,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE_BYTES,
    SUPPORTED_CAPABILITIES,
    SUPPORTED_PROVIDERS,
    DEFAULT_CONFIGS,
)
from app.models.science import Run, RunStatus
from app.schemas.ai import (
    AiProviderConfigResponse,
    AiProviderConfigUpdate,
    AiSettingsListResponse,
    AiTestConnectionResponse,
    AnalysisResponse,
    BatchAnalyzeResponse,
    ConfirmRequest,
    ConfirmResponse,
    ConverseRequest,
    ExtractedValueSchema,
    ImageConversationResponse,
    RunImageDetailResponse,
    RunImageListResponse,
    RunImageResponse,
    TagImageRequest,
)
from app.core.deps import get_current_user
from app.models.iam import User
from app.services.ai_config import invalidate_cache, mask_api_key
from app.services.ai_vision import analyze_image, continue_conversation
from app.services.audit import log_audit

router = APIRouter()


def _row_to_response(row: AiProviderConfig) -> AiProviderConfigResponse:
    return AiProviderConfigResponse(
        id=row.id,
        capability=row.capability,
        provider=row.provider,
        model_name=row.model_name,
        api_key_set=row.api_key is not None and len(row.api_key) > 0,
        api_key_hint=mask_api_key(row.api_key),
        base_url=row.base_url,
        is_enabled=row.is_enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/settings", response_model=AiSettingsListResponse)
async def list_ai_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AiProviderConfig).order_by(AiProviderConfig.capability)
    )
    rows = result.scalars().all()
    return AiSettingsListResponse(
        items=[_row_to_response(r) for r in rows]
    )


@router.put(
    "/settings/{capability}",
    response_model=AiProviderConfigResponse,
)
async def upsert_ai_setting(
    capability: str,
    body: AiProviderConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    if capability not in SUPPORTED_CAPABILITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported capability: {capability}. "
            f"Must be one of: {', '.join(SUPPORTED_CAPABILITIES)}",
        )

    if body.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported provider: {body.provider}. "
            f"Must be one of: {', '.join(SUPPORTED_PROVIDERS)}",
        )

    # Cloud providers require an API key (unless one is already saved)
    if body.provider != "ollama" and not body.api_key:
        result = await db.execute(
            select(AiProviderConfig).where(
                AiProviderConfig.capability == capability
            )
        )
        existing = result.scalar_one_or_none()
        if not existing or not existing.api_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Provider '{body.provider}' requires an API key.",
            )

    result = await db.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.capability == capability
        )
    )
    row = result.scalar_one_or_none()

    if row:
        row.provider = body.provider
        row.model_name = body.model_name
        row.base_url = body.base_url
        row.is_enabled = body.is_enabled
        # Only update api_key if a new one was provided
        if body.api_key is not None:
            row.api_key = body.api_key
    else:
        row = AiProviderConfig(
            capability=capability,
            provider=body.provider,
            model_name=body.model_name,
            api_key=body.api_key,
            base_url=body.base_url,
            is_enabled=body.is_enabled,
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)

    invalidate_cache(capability)

    return _row_to_response(row)


@router.post(
    "/settings/{capability}/test",
    response_model=AiTestConnectionResponse,
)
async def test_ai_connection(
    capability: str,
    db: AsyncSession = Depends(get_db),
):
    if capability not in SUPPORTED_CAPABILITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported capability: {capability}.",
        )

    result = await db.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.capability == capability,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return AiTestConnectionResponse(
            success=False,
            message=f"No configuration found for capability '{capability}'. "
            "Save a configuration first.",
        )

    if not row.is_enabled:
        return AiTestConnectionResponse(
            success=False,
            message=f"Capability '{capability}' is disabled.",
        )

    # Attempt a lightweight probe of the provider
    try:
        if row.provider == "ollama":
            import httpx

            base = row.base_url or "http://localhost:11434"
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(f"{base}/api/tags")
                if resp.status_code == 200:
                    models = [
                        m["name"] for m in resp.json().get("models", [])
                    ]
                    if any(row.model_name in m for m in models):
                        return AiTestConnectionResponse(
                            success=True,
                            message=f"Connected to Ollama. Model '{row.model_name}' is available.",
                        )
                    return AiTestConnectionResponse(
                        success=False,
                        message=f"Connected to Ollama but model '{row.model_name}' "
                        f"not found. Available: {', '.join(models[:5])}",
                    )
                return AiTestConnectionResponse(
                    success=False,
                    message=f"Ollama returned status {resp.status_code}.",
                )
        else:
            # For cloud providers, verify the API key format is plausible
            if not row.api_key:
                return AiTestConnectionResponse(
                    success=False,
                    message=f"No API key set for provider '{row.provider}'.",
                )
            return AiTestConnectionResponse(
                success=True,
                message=f"Configuration saved for {row.provider}:{row.model_name}. "
                "API key is set. Full validation occurs on first use.",
            )
    except Exception as exc:
        return AiTestConnectionResponse(
            success=False,
            message=f"Connection failed: {str(exc)}",
        )


# ── Image Upload & Retrieval ─────────────────────────────────────────


def _get_storage_path() -> str:
    return settings.image_storage_path


async def _get_active_run(run_id: uuid_mod.UUID, db: AsyncSession) -> Run:
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.post(
    "/runs/{run_id}/steps/{step_id}/images",
    response_model=RunImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_image(
    run_id: uuid_mod.UUID,
    step_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await _get_active_run(run_id, db)
    if run.status not in (RunStatus.ACTIVE, RunStatus.EDITED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run must be ACTIVE to upload images (current: {run.status}).",
        )

    # Validate mime type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported image type: {content_type}. "
            f"Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    if file_size > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image too large ({file_size} bytes). "
            f"Maximum: {MAX_IMAGE_SIZE_BYTES} bytes.",
        )

    # Build storage path
    ext = os.path.splitext(file.filename or "image.jpg")[1] or ".jpg"
    image_uuid = uuid_mod.uuid4()
    relative_path = f"{run_id}/{step_id}/{image_uuid}{ext}"
    storage_root = _get_storage_path()
    full_path = Path(storage_root) / relative_path

    # Write file to disk
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(content)

    # Create DB record
    image = RunImage(
        run_id=run_id,
        step_id=step_id,
        file_path=relative_path,
        original_filename=file.filename or "image.jpg",
        mime_type=content_type,
        file_size_bytes=file_size,
        uploaded_by_id=current_user.id,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)

    return RunImageResponse.model_validate(image)


@router.get(
    "/runs/{run_id}/images",
    response_model=RunImageListResponse,
)
async def list_run_images(
    run_id: uuid_mod.UUID,
    analyzed: Optional[bool] = Query(
        default=None,
        description="Filter by analysis status: true=has conversation, false=no conversation",
    ),
    db: AsyncSession = Depends(get_db),
):
    await _get_active_run(run_id, db)  # verify run exists

    query = select(RunImage).where(RunImage.run_id == run_id)

    if analyzed is not None:
        # Subquery: image IDs that have at least one conversation
        analyzed_ids = (
            select(ImageConversation.image_id)
            .distinct()
            .scalar_subquery()
        )
        if analyzed:
            query = query.where(RunImage.id.in_(analyzed_ids))
        else:
            query = query.where(RunImage.id.notin_(analyzed_ids))

    result = await db.execute(query.order_by(RunImage.created_at))
    rows = result.scalars().all()
    return RunImageListResponse(
        items=[RunImageResponse.model_validate(r) for r in rows]
    )


@router.get(
    "/runs/{run_id}/images/{image_id}",
    response_model=RunImageDetailResponse,
)
async def get_run_image(
    run_id: uuid_mod.UUID,
    image_id: uuid_mod.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RunImage).where(
            RunImage.id == image_id,
            RunImage.run_id == run_id,
        )
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")

    # Get latest conversation if any
    conv_result = await db.execute(
        select(ImageConversation)
        .where(ImageConversation.image_id == image_id)
        .order_by(ImageConversation.created_at.desc())
        .limit(1)
    )
    conversation = conv_result.scalar_one_or_none()

    resp = RunImageDetailResponse.model_validate(image)
    if conversation:
        resp.conversation = ImageConversationResponse.model_validate(
            conversation
        )
    return resp


# ── Analyze / Converse / Confirm ──────────────────────────────────────


def _get_step_info(run: Run, step_id: str) -> tuple[str, dict]:
    """Extract step name and paramSchema from the run's graph."""
    nodes = run.graph.get("nodes", [])
    for node in nodes:
        if node.get("id") == step_id:
            data = node.get("data", {})
            name = data.get("label", step_id)
            param_schema = data.get("paramSchema", {})
            return name, param_schema
    return step_id, {}


async def _get_image_with_run(
    run_id: uuid_mod.UUID,
    image_id: uuid_mod.UUID,
    db: AsyncSession,
) -> tuple[Run, RunImage]:
    """Fetch run and image, raising 404 if either is missing."""
    run = await _get_active_run(run_id, db)
    result = await db.execute(
        select(RunImage).where(
            RunImage.id == image_id,
            RunImage.run_id == run_id,
        )
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")
    return run, image


@router.post(
    "/runs/{run_id}/images/{image_id}/analyze",
    response_model=AnalysisResponse,
)
async def analyze_run_image(
    run_id: uuid_mod.UUID,
    image_id: uuid_mod.UUID,
    db: AsyncSession = Depends(get_db),
):
    run, image = await _get_image_with_run(run_id, image_id, db)

    if run.status not in (RunStatus.ACTIVE, RunStatus.EDITED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run must be ACTIVE to analyze images (current: {run.status}).",
        )

    step_name, param_schema = _get_step_info(run, image.step_id)
    image_full_path = str(Path(_get_storage_path()) / image.file_path)

    try:
        ai_result = await analyze_image(
            image_path=image_full_path,
            step_name=step_name,
            param_schema=param_schema,
            db=db,
        )
    except Exception as exc:
        # Create a failed conversation record
        conv = ImageConversation(
            image_id=image.id,
            messages=[{"role": "system", "content": f"Analysis failed: {exc}"}],
            extracted_values={},
            status="failed",
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI analysis failed: {str(exc)}",
        )

    # Determine conversation status
    conv_status = (
        "needs_clarification" if ai_result.needs_clarification else "analyzed"
    )

    # Build extracted values dict for storage
    extracted_dict = {
        ev.field_key: {
            "value": ev.value,
            "unit": ev.unit,
            "confidence": ev.confidence,
            "label": ev.field_label,
        }
        for ev in ai_result.extracted_values
    }

    # Create conversation record
    conv = ImageConversation(
        image_id=image.id,
        messages=[{"role": "assistant", "content": ai_result.message}],
        extracted_values=extracted_dict,
        status=conv_status,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return AnalysisResponse(
        conversation=ImageConversationResponse.model_validate(conv),
        message=ai_result.message,
        extracted_values=[
            ExtractedValueSchema(
                field_key=ev.field_key,
                field_label=ev.field_label,
                value=ev.value,
                unit=ev.unit,
                confidence=ev.confidence,
            )
            for ev in ai_result.extracted_values
        ],
        needs_clarification=ai_result.needs_clarification,
    )


@router.post(
    "/runs/{run_id}/images/{image_id}/converse",
    response_model=AnalysisResponse,
)
async def converse_about_image(
    run_id: uuid_mod.UUID,
    image_id: uuid_mod.UUID,
    body: ConverseRequest,
    db: AsyncSession = Depends(get_db),
):
    run, image = await _get_image_with_run(run_id, image_id, db)

    # Get existing conversation
    conv_result = await db.execute(
        select(ImageConversation)
        .where(ImageConversation.image_id == image_id)
        .order_by(ImageConversation.created_at.desc())
        .limit(1)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=404,
            detail="No conversation found. Call /analyze first.",
        )

    step_name, param_schema = _get_step_info(run, image.step_id)
    image_full_path = str(Path(_get_storage_path()) / image.file_path)

    # Append user message to history
    conv.messages = [*conv.messages, {"role": "user", "content": body.message}]

    try:
        ai_result = await continue_conversation(
            image_path=image_full_path,
            step_name=step_name,
            param_schema=param_schema,
            messages=conv.messages,
            user_reply=body.message,
            db=db,
        )
    except Exception as exc:
        conv.status = "failed"
        conv.messages = [
            *conv.messages,
            {"role": "system", "content": f"Analysis failed: {exc}"},
        ]
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI analysis failed: {str(exc)}",
        )

    # Append AI response
    conv.messages = [
        *conv.messages,
        {"role": "assistant", "content": ai_result.message},
    ]

    # Update extracted values
    extracted_dict = {
        ev.field_key: {
            "value": ev.value,
            "unit": ev.unit,
            "confidence": ev.confidence,
            "label": ev.field_label,
        }
        for ev in ai_result.extracted_values
    }
    conv.extracted_values = extracted_dict
    conv.status = (
        "needs_clarification" if ai_result.needs_clarification else "analyzed"
    )

    await db.commit()
    await db.refresh(conv)

    return AnalysisResponse(
        conversation=ImageConversationResponse.model_validate(conv),
        message=ai_result.message,
        extracted_values=[
            ExtractedValueSchema(
                field_key=ev.field_key,
                field_label=ev.field_label,
                value=ev.value,
                unit=ev.unit,
                confidence=ev.confidence,
            )
            for ev in ai_result.extracted_values
        ],
        needs_clarification=ai_result.needs_clarification,
    )


@router.post(
    "/runs/{run_id}/images/{image_id}/confirm",
    response_model=ConfirmResponse,
)
async def confirm_image_values(
    run_id: uuid_mod.UUID,
    image_id: uuid_mod.UUID,
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run, image = await _get_image_with_run(run_id, image_id, db)

    if not body.values:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No values provided to confirm.",
        )

    # Get conversation
    conv_result = await db.execute(
        select(ImageConversation)
        .where(ImageConversation.image_id == image_id)
        .order_by(ImageConversation.created_at.desc())
        .limit(1)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=404,
            detail="No conversation found. Call /analyze first.",
        )

    # Write confirmed values to run.execution_data
    step_id = image.step_id
    exec_data = dict(run.execution_data or {})
    step_data = dict(exec_data.get(step_id, {}))
    results = dict(step_data.get("results", {}))

    for field_key, value in body.values.items():
        results[field_key] = value

    step_data["results"] = results
    if step_data.get("status") == "pending":
        step_data["status"] = "in_progress"
    exec_data[step_id] = step_data
    run.execution_data = exec_data

    # Mark conversation as confirmed
    conv.status = "confirmed"
    conv.extracted_values = {
        k: {"value": v, "confirmed": True}
        for k, v in body.values.items()
    }

    # Audit log
    await log_audit(
        db=db,
        actor_id=current_user.id,
        action="IMAGE_CONFIRM",
        entity_type="Run",
        entity_id=run.id,
        changes={
            "image_id": str(image.id),
            "step_id": step_id,
            "confirmed_values": body.values,
        },
    )

    await db.commit()
    await db.refresh(conv)

    return ConfirmResponse(
        conversation=ImageConversationResponse.model_validate(conv),
        execution_data_updated=True,
    )


# ── Tag & Batch Analyze ──────────────────────────────────────────────


@router.put(
    "/runs/{run_id}/images/{image_id}/tag",
    response_model=RunImageResponse,
)
async def tag_image(
    run_id: uuid_mod.UUID,
    image_id: uuid_mod.UUID,
    body: TagImageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Set parameter tags on an image (which param_schema keys it relates to)."""
    result = await db.execute(
        select(RunImage).where(
            RunImage.id == image_id,
            RunImage.run_id == run_id,
        )
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")

    image.parameter_tags = body.parameter_tags
    await db.commit()
    await db.refresh(image)
    return RunImageResponse.model_validate(image)


@router.post(
    "/runs/{run_id}/analyze-pending",
    response_model=BatchAnalyzeResponse,
)
async def analyze_pending_images(
    run_id: uuid_mod.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Sequentially analyze all unanalyzed images in a run."""
    run = await _get_active_run(run_id, db)

    if run.status not in (RunStatus.ACTIVE, RunStatus.EDITED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run must be ACTIVE to analyze images (current: {run.status}).",
        )

    # Find images without any conversation
    analyzed_ids = (
        select(ImageConversation.image_id)
        .distinct()
        .scalar_subquery()
    )
    result = await db.execute(
        select(RunImage)
        .where(
            RunImage.run_id == run_id,
            RunImage.id.notin_(analyzed_ids),
        )
        .order_by(RunImage.created_at)
    )
    pending_images = result.scalars().all()

    succeeded = 0
    failed = 0

    for image in pending_images:
        step_name, param_schema = _get_step_info(run, image.step_id)
        image_full_path = str(Path(_get_storage_path()) / image.file_path)

        try:
            ai_result = await analyze_image(
                image_path=image_full_path,
                step_name=step_name,
                param_schema=param_schema,
                db=db,
            )

            conv_status = (
                "needs_clarification"
                if ai_result.needs_clarification
                else "analyzed"
            )
            extracted_dict = {
                ev.field_key: {
                    "value": ev.value,
                    "unit": ev.unit,
                    "confidence": ev.confidence,
                    "label": ev.field_label,
                }
                for ev in ai_result.extracted_values
            }
            conv = ImageConversation(
                image_id=image.id,
                messages=[
                    {"role": "assistant", "content": ai_result.message}
                ],
                extracted_values=extracted_dict,
                status=conv_status,
            )
            db.add(conv)
            await db.commit()
            succeeded += 1
        except Exception:
            # Record failure but continue with remaining images
            conv = ImageConversation(
                image_id=image.id,
                messages=[
                    {"role": "system", "content": "Batch analysis failed"}
                ],
                extracted_values={},
                status="failed",
            )
            db.add(conv)
            await db.commit()
            failed += 1

    return BatchAnalyzeResponse(
        total=len(pending_images),
        succeeded=succeeded,
        failed=failed,
    )
