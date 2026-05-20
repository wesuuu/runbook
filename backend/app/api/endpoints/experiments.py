import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.deps import get_current_user, get_or_404, require_active_subscription
from app.db.session import get_db
from app.models.iam import ObjectType, PermissionLevel, User
from app.models.protocols import Protocol
from app.models.runs import Experiment, Run
from app.schemas.runs import (
    ExperimentCreate,
    ExperimentNote,
    ExperimentNoteCreate,
    ExperimentNoteListResponse,
    ExperimentResponse,
    ExperimentStatus,
    ExperimentUpdate,
    RunResponse,
)
from app.services.core.audit import log_audit
from app.services.core.permissions import check_permission

logger = logging.getLogger(__name__)

router = APIRouter()


def _experiment_dict(exp: Experiment) -> dict:
    """Convert Experiment ORM instance to a dict for ExperimentResponse."""
    return {
        "id": exp.id,
        "project_id": exp.project_id,
        "name": exp.name,
        "description": exp.description,
        "content": exp.content or {},
        "status": exp.status if isinstance(exp.status, str) else exp.status.value,
        "notes": [ExperimentNote(**n) for n in (exp.notes or [])],
        "created_at": exp.created_at,
        "updated_at": exp.updated_at,
    }


# --- CRUD ---


@router.post("/experiments", response_model=ExperimentResponse, status_code=201)
async def create_experiment(
    exp_in: ExperimentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp_in.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    experiment = Experiment(
        name=exp_in.name,
        project_id=exp_in.project_id,
        description=exp_in.description,
    )
    db.add(experiment)
    await db.flush()

    await log_audit(
        db,
        actor_id=user.id,
        action="CREATE",
        entity_type="Experiment",
        entity_id=experiment.id,
        changes={"name": exp_in.name},
    )
    await db.commit()
    await db.refresh(experiment)

    return ExperimentResponse(
        **_experiment_dict(experiment),
        runs=[],
        run_count=0,
    )


@router.get("/projects/{project_id}/experiments")
async def list_experiments(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        project_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    result = await db.execute(
        select(Experiment, func.count(Run.id).label("run_count"))
        .outerjoin(Run, Run.experiment_id == Experiment.id)
        .where(Experiment.project_id == project_id)
        .group_by(Experiment.id)
        .order_by(Experiment.created_at.desc())
    )
    rows = result.all()

    return [
        ExperimentResponse(
            **_experiment_dict(exp),
            runs=[],
            run_count=cnt,
        )
        for exp, cnt in rows
    ]


@router.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exp = await get_or_404(db, Experiment, experiment_id)

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    run_result = await db.execute(select(Run).where(Run.experiment_id == experiment_id))
    runs = list(run_result.scalars().all())

    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[RunResponse.model_validate(r) for r in runs],
        run_count=len(runs),
    )


@router.put("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def update_experiment(
    experiment_id: UUID,
    update_data: ExperimentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    changes = {}
    for field in ("name", "description", "content", "status"):
        value = getattr(update_data, field)
        if value is not None:
            old = getattr(exp, field)
            resolved = value.value if isinstance(value, Enum) else value
            setattr(exp, field, resolved)
            changes[field] = {"old": old, "new": resolved}
    if update_data.content is not None:
        flag_modified(exp, "content")

    if changes:
        await log_audit(
            db,
            actor_id=user.id,
            action="UPDATE",
            entity_type="Experiment",
            entity_id=exp.id,
            changes=changes,
        )

    await db.commit()
    await db.refresh(exp)

    # Load run count
    count_result = await db.execute(
        select(func.count(Run.id)).where(Run.experiment_id == experiment_id)
    )
    run_count = count_result.scalar() or 0

    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[],
        run_count=run_count,
    )


@router.delete("/experiments/{experiment_id}")
async def archive_experiment(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    exp.status = ExperimentStatus.ARCHIVED.value

    # Cascade archive all associated runs
    await db.execute(
        update(Run)
        .where(Run.experiment_id == experiment_id)
        .values(status=ExperimentStatus.ARCHIVED.value)
    )

    await log_audit(
        db,
        actor_id=user.id,
        action="ARCHIVE",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={"status": "ARCHIVED"},
    )
    await db.commit()
    return {"status": "archived"}


# --- Run Management ---


class _ExperimentRunBody(PydanticBaseModel):
    """Either link an existing run (run_id) or create a new one (name + protocol_id)."""

    run_id: Optional[UUID] = None
    name: Optional[str] = None
    project_id: Optional[UUID] = None
    protocol_id: Optional[UUID] = None


@router.post("/experiments/{experiment_id}/runs", status_code=201)
async def add_run_to_experiment(
    experiment_id: UUID,
    body: _ExperimentRunBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    if body.run_id:
        # Link existing run
        run = await get_or_404(db, Run, body.run_id)
        if run.project_id != exp.project_id:
            raise HTTPException(400, "Run must be in the same project")
        if run.experiment_id is not None:
            raise HTTPException(409, "Run already belongs to another experiment")
        run.experiment_id = experiment_id

        await log_audit(
            db,
            actor_id=user.id,
            action="UPDATE",
            entity_type="Run",
            entity_id=run.id,
            changes={"experiment_id": str(experiment_id)},
        )
        await db.commit()
        await db.refresh(run)
        return RunResponse.model_validate(run)
    else:
        # Create new run within experiment
        if not body.name:
            raise HTTPException(422, "name is required to create a new run")

        run = Run(
            name=body.name,
            project_id=exp.project_id,
            protocol_id=body.protocol_id,
            experiment_id=experiment_id,
        )

        if body.protocol_id:
            protocol = await get_or_404(db, Protocol, body.protocol_id)
            if protocol.status and protocol.status.upper() == "ARCHIVED":
                raise HTTPException(400, "Cannot create run from archived protocol")
            run.graph = protocol.graph.copy() if protocol.graph else {}

        db.add(run)
        await db.flush()

        await log_audit(
            db,
            actor_id=user.id,
            action="CREATE",
            entity_type="Run",
            entity_id=run.id,
            changes={
                "name": body.name,
                "experiment_id": str(experiment_id),
            },
        )
        await db.commit()
        await db.refresh(run)
        return RunResponse.model_validate(run)


@router.delete("/experiments/{experiment_id}/runs/{run_id}")
async def unlink_run_from_experiment(
    experiment_id: UUID,
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    run = await get_or_404(db, Run, run_id)
    if run.experiment_id != experiment_id:
        raise HTTPException(400, "Run is not in this experiment")

    run.experiment_id = None

    await log_audit(
        db,
        actor_id=user.id,
        action="UPDATE",
        entity_type="Run",
        entity_id=run.id,
        changes={"experiment_id": None},
    )
    await db.commit()
    return {"status": "unlinked"}


# --- Notes ---


@router.post(
    "/experiments/{experiment_id}/notes",
    response_model=ExperimentNote,
    status_code=201,
)
async def add_experiment_note(
    experiment_id: UUID,
    body: ExperimentNoteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    note = {
        "id": str(uuid_mod.uuid4()),
        "content": body.content,
        "author_id": str(user.id),
        "author_name": user.full_name or user.email,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "flags": body.flags,
    }

    notes_list = list(exp.notes or [])
    notes_list.append(note)
    exp.notes = notes_list
    flag_modified(exp, "notes")

    await log_audit(
        db,
        actor_id=user.id,
        action="NOTE_ADDED",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={"note_id": note["id"]},
    )
    await db.commit()
    return ExperimentNote(**note)


@router.get(
    "/experiments/{experiment_id}/notes",
    response_model=ExperimentNoteListResponse,
)
async def list_experiment_notes(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exp = await get_or_404(db, Experiment, experiment_id)

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    return ExperimentNoteListResponse(
        items=[ExperimentNote(**n) for n in (exp.notes or [])]
    )
