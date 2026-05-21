import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.deps import get_current_user, get_or_404, require_active_subscription
from app.db.session import get_db
from app.models.iam import ObjectType, PermissionLevel, User
from app.models.projects import Project
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
from app.services.experiments.status import (
    derive_lifecycle_status,
    lifecycle_counts_from_runs,
)
from app.services.slugs import assign_slug_or_422

logger = logging.getLogger(__name__)

router = APIRouter()


def _experiment_dict(exp: Experiment) -> dict:
    """Convert Experiment ORM instance to a dict for ExperimentResponse.

    `lifecycle_status` is NOT set here — it depends on child runs and is
    supplied by each handler from run counts.
    """
    return {
        "id": exp.id,
        "project_id": exp.project_id,
        "slug": exp.slug,
        "project_slug": exp.project_slug,
        "name": exp.name,
        "description": exp.description,
        "objective": exp.objective,
        "success_criteria": list(exp.success_criteria or []),
        "created_by_id": exp.created_by_id,
        "content": exp.content or {},
        "status": exp.status if isinstance(exp.status, str) else exp.status.value,
        "notes": [ExperimentNote(**n) for n in (exp.notes or [])],
        "created_at": exp.created_at,
        "updated_at": exp.updated_at,
    }


async def _run_lifecycle_counts(
    db: AsyncSession, experiment_id: UUID
) -> tuple[int, int, int]:
    """Return (run_count, live_run_count, open_run_count) for one experiment."""
    row = (
        await db.execute(
            select(
                func.count(Run.id),
                func.count(Run.id).filter(Run.status != "ARCHIVED"),
                func.count(Run.id).filter(
                    and_(Run.status != "ARCHIVED", Run.status != "COMPLETED")
                ),
            ).where(Run.experiment_id == experiment_id)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2])


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
        objective=exp_in.objective,
        success_criteria=exp_in.success_criteria,
        created_by_id=user.id,
    )
    experiment.slug = await assign_slug_or_422(
        db,
        Experiment,
        Experiment.project_id,
        experiment.project_id,
        experiment.name,
        "experiment",
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
    await db.refresh(experiment, attribute_names=["project"])

    return ExperimentResponse(
        **_experiment_dict(experiment),
        runs=[],
        run_count=0,
        lifecycle_status=derive_lifecycle_status(experiment.status, 0, 0),
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
        select(
            Experiment,
            func.count(Run.id).label("run_count"),
            func.count(Run.id).filter(Run.status != "ARCHIVED").label("live"),
            func.count(Run.id)
            .filter(and_(Run.status != "ARCHIVED", Run.status != "COMPLETED"))
            .label("open"),
        )
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
            lifecycle_status=derive_lifecycle_status(exp.status, live, open_),
        )
        for exp, cnt, live, open_ in rows
    ]


@router.get(
    "/experiments/by-slug/{project_slug}/{slug}",
    response_model=ExperimentResponse,
)
async def get_experiment_by_slug(
    project_slug: str,
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Look up an experiment by project slug + experiment slug."""
    result = await db.execute(
        select(Experiment)
        .join(Project, Experiment.project_id == Project.id)
        .where(
            Project.organization_id == user.selected_org_id,
            Project.slug == project_slug,
            Experiment.slug == slug,
        )
    )
    exp = result.scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    run_result = await db.execute(select(Run).where(Run.experiment_id == exp.id))
    runs = list(run_result.scalars().all())

    live, open_ = lifecycle_counts_from_runs(runs)
    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[RunResponse.model_validate(r) for r in runs],
        run_count=len(runs),
        lifecycle_status=derive_lifecycle_status(exp.status, live, open_),
    )


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

    live, open_ = lifecycle_counts_from_runs(runs)
    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[RunResponse.model_validate(r) for r in runs],
        run_count=len(runs),
        lifecycle_status=derive_lifecycle_status(exp.status, live, open_),
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

    if update_data.name is not None and update_data.name != exp.name:
        exp.slug = await assign_slug_or_422(
            db,
            Experiment,
            Experiment.project_id,
            exp.project_id,
            update_data.name,
            "experiment",
            exclude_id=exp.id,
        )

    changes = {}
    for field in ("name", "description", "content", "objective", "success_criteria"):
        value = getattr(update_data, field)
        if value is not None:
            old = getattr(exp, field)
            resolved = value.value if isinstance(value, Enum) else value
            setattr(exp, field, resolved)
            changes[field] = {"old": old, "new": resolved}
    if update_data.content is not None:
        flag_modified(exp, "content")
    if update_data.success_criteria is not None:
        flag_modified(exp, "success_criteria")

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

    run_count, live, open_ = await _run_lifecycle_counts(db, experiment_id)

    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[],
        run_count=run_count,
        lifecycle_status=derive_lifecycle_status(exp.status, live, open_),
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

        run.slug = await assign_slug_or_422(
            db, Run, Run.project_id, run.project_id, run.name, "run"
        )

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
