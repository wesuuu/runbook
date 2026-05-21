"""Unit tests for the F-0092 dashboard response schema."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from app.schemas.dashboard import (
    BlockerReason,
    CalibrationItem,
    Counters,
    DashboardResponse,
    LabStatus,
    MyWork,
    RunSummary,
    SignoffItem,
)


def test_counters_default_to_zero():
    c = Counters()
    assert (c.runs_blocked, c.calibrations_due, c.signoffs_pending,
            c.active_runs) == (0, 0, 0, 0)


def test_run_summary_carries_blockers():
    rs = RunSummary(
        id=uuid4(),
        name="R",
        project_id=uuid4(),
        project_name="P",
        status="PLANNED",
        updated_at=datetime.now(timezone.utc),
        blockers=[BlockerReason(code="LANES_UNASSIGNED", label="No one assigned")],
    )
    assert rs.blockers[0].code == "LANES_UNASSIGNED"
    # default empty for unblocked runs
    assert RunSummary(
        id=uuid4(), name="R2", project_id=uuid4(), project_name="P",
        status="ACTIVE", updated_at=datetime.now(timezone.utc),
    ).blockers == []


def test_lab_status_defaults_are_empty():
    ls = LabStatus()
    assert ls.calibration.overdue == []
    assert ls.calibration.due_soon == []
    assert ls.awaiting_signoff == []


def test_dashboard_response_assembles():
    resp = DashboardResponse(
        my_work=MyWork(),
        lab_status=LabStatus(),
        activity=[],
        counters=Counters(),
    )
    assert resp.my_work.needs_action == []
    assert resp.my_work.in_progress == []
    assert resp.my_work.planned == []


def test_calibration_item_and_signoff_item():
    CalibrationItem(
        equipment_id=uuid4(), name="Centrifuge", site_name="Lab A",
        next_calibration_date=date.today(), state="overdue",
    )
    SignoffItem(kind="run", entity_id=uuid4(), name="Run 7",
                detail="Missing OPERATOR")
