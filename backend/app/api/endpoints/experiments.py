import asyncio
import logging
import time
import uuid as uuid_mod
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import and_, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload, selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.deps import (
    get_current_user,
    get_or_404,
    require_active_subscription,
    require_org_role,
)
from app.db.session import get_db
from app.models.iam import ObjectType, OrgRole, PermissionLevel, User
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Experiment, Run
from app.schemas.runs import (
    ConclusionUnlockRequest,
    ExperimentCreate,
    ExperimentNote,
    ExperimentNoteCreate,
    ExperimentNoteListResponse,
    ExperimentOwner,
    ExperimentResponse,
    ExperimentRunSummary,
    ExperimentStatus,
    ExperimentSummary,
    ExperimentUpdate,
    RunResponse,
)
from app.services.core.audit import log_audit
from app.services.core.permissions import check_permission, get_visible_project_ids
from app.services.experiments import pdf_export
from app.services.experiments.lock_guard import locked_409
from app.services.experiments.observations import aggregate_observations
from app.services.experiments.status import (
    derive_lifecycle_status,
    lifecycle_counts_from_runs,
)
from app.services.slugs import assign_slug_or_422

logger = logging.getLogger(__name__)
_log = logger

EXPORT_TIMEOUT_SECONDS = 30.0

router = APIRouter()


def _owner_initials(full_name: str | None, email: str) -> str:
    """First letters of the first two name words; else first email char."""
    if full_name and full_name.strip():
        words = full_name.split()
        return "".join(w[0] for w in words[:2]).upper()
    return email[:1].upper()


def _owner_summary(creator) -> "ExperimentOwner | None":
    if creator is None:
        return None
    name = creator.full_name or creator.email
    return ExperimentOwner(
        id=creator.id,
        name=name,
        initials=_owner_initials(creator.full_name, creator.email),
    )


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
        "conclusion": exp.conclusion,
        "conclusion_locked_at": exp.conclusion_locked_at,
        "conclusion_locked_by_id": exp.conclusion_locked_by_id,
        "conclusion_locked_by_name": exp.conclusion_locked_by_name,
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
            lifecycle_status=derive_lifecycle_status(
                exp.status, live, open_, conclusion_locked=exp.conclusion_locked_at is not None
            ),
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
        lifecycle_status=derive_lifecycle_status(
            exp.status, live, open_, conclusion_locked=exp.conclusion_locked_at is not None
        ),
    )


@router.get("/experiments", response_model=list[ExperimentSummary])
async def list_all_experiments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Org-wide experiments index (F-0093 §1.1).

    Org isolation is enforced by scoping to `user.selected_org_id`;
    permission filtering reuses `get_visible_project_ids`. Read endpoint —
    no `require_active_subscription` (a lapsed subscription must not block
    reading one's own experiments).
    """
    if user.selected_org_id is None:
        raise HTTPException(400, "No organization selected")

    visible_project_ids = await get_visible_project_ids(
        db, user.id, user.selected_org_id
    )
    if not visible_project_ids:
        return []

    started = datetime.now(timezone.utc)

    # Experiments + owner, newest-touched first.
    #   - selectinload(created_by): one batched query for owner avatars.
    #   - lazyload(project): `Experiment.project` is `lazy="selectin"` on the
    #     model; this endpoint reads slug/name from the JOIN and never touches
    #     `exp.project`, so suppress the relationship to avoid a redundant
    #     org-wide project fetch on every call.
    #   - limit(500): safety backstop. The org-wide index is unpaginated in
    #     this slice (§1.1 — pagination is a deferred follow-up); 500 caps a
    #     pathological org so an unbounded result set can't OOM the worker.
    exp_rows = (
        await db.execute(
            select(Experiment, Project.slug, Project.name)
            .join(Project, Experiment.project_id == Project.id)
            .where(Experiment.project_id.in_(visible_project_ids))
            .options(
                selectinload(Experiment.created_by),
                lazyload(Experiment.project),
            )
            .order_by(Experiment.updated_at.desc())
            .limit(500)
        )
    ).all()
    if not exp_rows:
        return []

    experiment_ids = [exp.id for exp, _, _ in exp_rows]

    # Run aggregates per experiment — uncapped, used for run_count + lifecycle.
    agg_rows = (
        await db.execute(
            select(
                Run.experiment_id,
                func.count(Run.id),
                func.count(Run.id).filter(Run.status != "ARCHIVED"),
                func.count(Run.id).filter(
                    and_(Run.status != "ARCHIVED", Run.status != "COMPLETED")
                ),
            )
            .where(Run.experiment_id.in_(experiment_ids))
            .group_by(Run.experiment_id)
        )
    ).all()
    agg = {
        exp_id: (int(total), int(live), int(open_))
        for exp_id, total, live, open_ in agg_rows
    }

    # Capped run summaries — 60 oldest runs per experiment, in SQL.
    ranked = (
        select(
            Run.experiment_id.label("experiment_id"),
            Run.status.label("status"),
            Run.outcome.label("outcome"),
            func.row_number()
            .over(partition_by=Run.experiment_id, order_by=Run.created_at.asc())
            .label("rn"),
        )
        .where(Run.experiment_id.in_(experiment_ids))
        .subquery()
    )
    summary_rows = (
        await db.execute(
            select(ranked.c.experiment_id, ranked.c.status, ranked.c.outcome)
            .where(ranked.c.rn <= 60)
            .order_by(ranked.c.experiment_id, ranked.c.rn)
        )
    ).all()
    summaries: dict = {}
    for exp_id, status, outcome in summary_rows:
        summaries.setdefault(exp_id, []).append(
            ExperimentRunSummary(status=status, outcome=outcome)
        )

    results = []
    for exp, project_slug, project_name in exp_rows:
        total, live, open_ = agg.get(exp.id, (0, 0, 0))
        results.append(
            ExperimentSummary(
                id=exp.id,
                slug=exp.slug,
                name=exp.name,
                objective=exp.objective,
                project_id=exp.project_id,
                project_slug=project_slug,
                project_name=project_name,
                lifecycle_status=derive_lifecycle_status(
                    exp.status, live, open_, conclusion_locked=exp.conclusion_locked_at is not None
                ),
                run_count=total,
                run_summaries=summaries.get(exp.id, []),
                owner=_owner_summary(exp.created_by),
                created_at=exp.created_at,
                updated_at=exp.updated_at,
            )
        )

    elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    if elapsed_ms > 500:
        logger.warning(
            "GET /experiments slow: %.0f ms, org=%s, experiments=%d",
            elapsed_ms,
            user.selected_org_id,
            len(results),
        )
    return results


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
        lifecycle_status=derive_lifecycle_status(
            exp.status, live, open_, conclusion_locked=exp.conclusion_locked_at is not None
        ),
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

    # Slug is intentionally NOT regenerated on rename — keeps URLs and
    # bookmarks stable after the experiment is created (C2).

    # F-0043: lock guard — while locked, ALL mutations 409.
    if exp.conclusion_locked_at is not None:
        raise locked_409(
            "Experiment conclusion is locked. Admin must unlock first."
        )

    changes = {}
    for field in (
        "name", "description", "content", "objective",
        "success_criteria", "conclusion",
    ):
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
        lifecycle_status=derive_lifecycle_status(
            exp.status, live, open_, conclusion_locked=exp.conclusion_locked_at is not None
        ),
    )


@router.post(
    "/experiments/{experiment_id}/conclusion/lock",
    response_model=ExperimentResponse,
)
async def lock_experiment_conclusion(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, exp.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    # GxP signature durability: require profile name. Fall back to "User
    # {id}" instead of leaking email into the permanent record.
    user_name = (user.full_name or "").strip() or f"User {user.id}"

    # Atomic UPDATE: race-free against concurrent run transitions AND against
    # concurrent lock attempts (asyncpg returns a row when the WHERE matches;
    # asyncpg's `result.rowcount` is unreliable for `UPDATE ... RETURNING`,
    # so we branch on the returned row count via `result.all()`).
    #
    # Additional guard: require at least one COMPLETED run. Without this an
    # experiment whose only runs are ARCHIVED — which reads as DRAFT via
    # lifecycle_counts_from_runs — could be locked into COMPLETE state, a
    # contradiction.
    result = await db.execute(
        text(
            """
            UPDATE experiments
            SET conclusion_locked_at = NOW(),
                conclusion_locked_by_id = :user_id,
                conclusion_locked_by_name = :user_name
            WHERE id = :exp_id
              AND conclusion_locked_at IS NULL
              AND conclusion IS NOT NULL
              AND length(trim(conclusion)) > 0
              AND EXISTS (
                SELECT 1 FROM runs
                WHERE experiment_id = :exp_id
                  AND status = 'COMPLETED'
              )
              AND NOT EXISTS (
                SELECT 1 FROM runs
                WHERE experiment_id = :exp_id
                  AND status IN ('PLANNED', 'ACTIVE', 'EDITED')
              )
            RETURNING id, conclusion
            """
        ),
        {"exp_id": exp.id, "user_id": user.id, "user_name": user_name},
    )
    rows = result.all()
    if not rows:
        # Disambiguate the failure for the client. Re-read the row in the
        # same transaction; `db.refresh()` reads from snapshot which is
        # acceptable here because we're branching on already-committed state.
        await db.refresh(exp)
        has_completed = await db.scalar(
            select(func.count(Run.id)).where(
                Run.experiment_id == exp.id, Run.status == "COMPLETED"
            )
        )
        if exp.conclusion_locked_at is not None:
            code, message = "ALREADY_LOCKED", "This experiment is already locked. Refresh and try again."
        elif not (exp.conclusion or "").strip():
            code, message = "EMPTY_CONCLUSION", "Write a conclusion before locking."
        elif not has_completed:
            code, message = "NO_COMPLETED_RUNS", "At least one run must be COMPLETED before locking."
        else:
            code, message = "OPEN_RUNS", "This experiment has open runs. Refresh and try again."
        raise HTTPException(409, {"code": code, "message": message})

    # Atomic audit: log_audit only db.add()s the row. Insert it BEFORE the
    # single commit so business state and audit row land together. If
    # log_audit raises, the UPDATE rolls back too. See projects.py for the
    # established pattern.
    locked_row = rows[0]
    await log_audit(
        db,
        actor_id=user.id,
        action="conclusion.lock",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={"conclusion_snapshot": locked_row.conclusion},
    )
    await db.commit()
    await db.refresh(exp)

    run_count, live, open_ = await _run_lifecycle_counts(db, experiment_id)
    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[],
        run_count=run_count,
        lifecycle_status=derive_lifecycle_status(
            exp.status, live, open_, conclusion_locked=True,
        ),
    )


@router.post(
    "/experiments/{experiment_id}/conclusion/unlock",
    response_model=ExperimentResponse,
)
async def unlock_experiment_conclusion(
    experiment_id: UUID,
    body: ConclusionUnlockRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
    __: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    exp = await get_or_404(db, Experiment, experiment_id)

    conclusion_before = exp.conclusion
    locked_by_before = exp.conclusion_locked_by_name
    locked_at_before = exp.conclusion_locked_at
    result = await db.execute(
        text(
            """
            UPDATE experiments
            SET conclusion_locked_at = NULL,
                conclusion_locked_by_id = NULL,
                conclusion_locked_by_name = NULL
            WHERE id = :exp_id
              AND conclusion_locked_at IS NOT NULL
            RETURNING id
            """
        ),
        {"exp_id": exp.id},
    )
    rows = result.all()
    if not rows:
        raise HTTPException(
            409, {"code": "ALREADY_UNLOCKED", "message": "Not locked"},
        )

    # Atomic audit: insert before single commit. See lock endpoint above.
    await log_audit(
        db,
        actor_id=user.id,
        action="conclusion.unlock",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={
            "reason": body.reason,
            "conclusion_before": conclusion_before,
            "locked_by_before": locked_by_before,
            "locked_at_before": locked_at_before.isoformat() if locked_at_before else None,
        },
    )
    await db.commit()
    await db.refresh(exp)

    run_count, live, open_ = await _run_lifecycle_counts(db, experiment_id)
    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[],
        run_count=run_count,
        lifecycle_status=derive_lifecycle_status(
            exp.status, live, open_, conclusion_locked=False,
        ),
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

    exp_status = (
        exp.status if isinstance(exp.status, str) else exp.status.value
    )
    if exp_status == "ARCHIVED":
        raise HTTPException(
            409,
            {
                "code": "EXPERIMENT_ARCHIVED",
                "message": "Cannot add or link runs to an archived experiment.",
            },
        )

    # TOCTOU: pin the experiment row + re-read locked state under that lock so
    # a concurrent POST /conclusion/lock cannot slip its UPDATE between our
    # check and our INSERT. The lock UPDATE's `NOT EXISTS open_runs` guard is
    # the matching half of this pair.
    await db.execute(
        text("SELECT 1 FROM experiments WHERE id = :id FOR UPDATE"),
        {"id": experiment_id},
    )
    await db.refresh(exp, ["conclusion_locked_at"])
    if exp.conclusion_locked_at is not None:
        raise locked_409("Cannot add a run to a locked experiment.")

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

    # F-0043: lock guard — unlinking a run from a locked experiment would
    # silently mutate the locked record's run set.
    if exp.conclusion_locked_at is not None:
        raise locked_409("Cannot unlink a run from a locked experiment.")

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

    if exp.conclusion_locked_at is not None:
        raise locked_409("Notes are frozen after the conclusion is locked.")

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


@router.delete(
    "/experiments/{experiment_id}/notes/{note_id}",
    status_code=204,
)
async def delete_experiment_note(
    experiment_id: UUID,
    note_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Delete a note. Only the original author may delete (audit-friendly)."""
    exp = await get_or_404(db, Experiment, experiment_id)

    if exp.conclusion_locked_at is not None:
        raise locked_409("Notes are frozen after the conclusion is locked.")

    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        exp.project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    notes_list = list(exp.notes or [])
    note_id_str = str(note_id)
    target = next((n for n in notes_list if n.get("id") == note_id_str), None)
    if target is None:
        raise HTTPException(404, "Note not found")

    if target.get("author_id") != str(user.id):
        raise HTTPException(403, "Only the note's author can delete it")

    exp.notes = [n for n in notes_list if n.get("id") != note_id_str]
    flag_modified(exp, "notes")

    await log_audit(
        db,
        actor_id=user.id,
        action="NOTE_DELETED",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={"note_id": note_id_str},
    )
    await db.commit()


# --- Observations ---


@router.get("/experiments/{experiment_id}/observations")
async def get_experiment_observations(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, exp.project_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    result = await aggregate_observations(db, experiment_id)
    response = JSONResponse(
        content={
            "items": [
                {
                    "id": i.id,
                    "source": i.source,
                    "source_id": str(i.source_id),
                    "run_label": i.run_label,
                    "run_slug": i.run_slug,
                    "run_project_slug": i.run_project_slug,
                    "flag": i.flag,
                    "body": i.body,
                    "author_name": i.author_name,
                    "created_at": i.created_at.isoformat(),
                }
                for i in result.items
            ],
            "truncated": result.truncated,
        },
    )
    response.headers["Cache-Control"] = "private, max-age=30"
    return response


@router.get("/experiments/{experiment_id}/export.pdf")
async def export_experiment_pdf(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, exp.project_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    # Project only the columns the PDF actually consumes. Run.notes and
    # Run.execution_data can be megabytes of JSONB per row — never load them
    # for an export that doesn't read them. ORDER BY locks byte-stable output
    # so two consecutive exports of a locked experiment produce identical PDFs
    # (regulators and tests both rely on this).
    runs_result = await db.execute(
        select(
            Run.id,
            Run.name,
            Run.graph,
            Run.status,
            Run.key_result_label,
            Run.key_result_value,
            Run.key_result_unit,
            Run.created_at,
        )
        .where(Run.experiment_id == experiment_id)
        .order_by(Run.created_at, Run.id)
    )
    runs = list(runs_result.all())

    obs = await aggregate_observations(db, experiment_id)
    obs_items = [
        {
            "flag": o.flag,
            "created_at": o.created_at.isoformat(),
            "body": o.body,
            "run_label": o.run_label,
        }
        for o in obs.items
    ]

    started = time.monotonic()
    try:
        loop = asyncio.get_running_loop()
        content = await asyncio.wait_for(
            loop.run_in_executor(
                pdf_export.PDF_EXECUTOR,
                pdf_export.generate_experiment_pdf,
                exp,
                runs,
                obs_items,
            ),
            timeout=EXPORT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _log.warning(
            "pdf_export_timeout experiment_id=%s slug=%s timeout_s=%s elapsed_ms=%d",
            experiment_id, exp.slug, EXPORT_TIMEOUT_SECONDS, elapsed_ms,
        )
        # Audit timeouts too — they are user-visible export failures and
        # appear in inspection histories.
        await log_audit(
            db,
            actor_id=user.id,
            action="export.pdf.timeout",
            entity_type="Experiment",
            entity_id=exp.id,
            changes={"timeout_s": EXPORT_TIMEOUT_SECONDS,
                     "elapsed_ms": elapsed_ms},
        )
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail={"code": "EXPORT_TIMEOUT", "message": "PDF generation timed out"},
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    # Anything over 5s is worth investigating before it crosses the 30s
    # timeout — emit as a warning so it surfaces in dashboards.
    log_fn = _log.warning if duration_ms > 5000 else _log.info
    log_fn(
        "pdf_export_ok experiment_id=%s slug=%s bytes=%d duration_ms=%d",
        experiment_id, exp.slug, len(content), duration_ms,
    )

    await log_audit(
        db,
        actor_id=user.id,
        action="export.pdf",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={"bytes": len(content), "duration_ms": duration_ms},
    )
    await db.commit()

    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="experiment-{exp.slug}.pdf"',
        },
    )
