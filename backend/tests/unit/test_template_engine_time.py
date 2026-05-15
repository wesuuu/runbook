"""QA-0008: time-axis surface in build_context."""

from app.services.protocols.template_engine import build_context


def test_time_disabled_by_default():
    ctx, _ = build_context(protocol_name="P")
    assert ctx["time_enabled"] is False
    assert ctx["start_time"] == ""


def test_time_enabled_propagates():
    ctx, _ = build_context(
        protocol_name="P",
        time_enabled=True,
        start_time="08:00",
    )
    assert ctx["time_enabled"] is True
    assert ctx["start_time"] == "08:00"


def test_scheduled_time_per_step_role_based():
    roles = [
        {
            "role_name": "Op",
            "process_name": "",
            "process_description": "",
            "steps": [
                {
                    "id": "s1",
                    "name": "A",
                    "duration_min": 30,
                    "params": {},
                    "param_schema": [],
                },
                {
                    "id": "s2",
                    "name": "B",
                    "duration_min": 15,
                    "params": {},
                    "param_schema": [],
                },
            ],
        }
    ]
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=True,
        roles_with_steps=roles,
        time_enabled=True,
        start_time="08:00",
    )
    role = ctx["roles"][0]
    assert role["steps"][0]["scheduled_at"] == "08:00"
    assert role["steps"][1]["scheduled_at"] == "08:30"


def test_actual_started_and_completed_per_step_from_execution_data():
    roles = [
        {
            "role_name": "Op",
            "process_name": "",
            "process_description": "",
            "steps": [
                {
                    "id": "s1",
                    "name": "A",
                    "duration_min": 30,
                    "params": {},
                    "param_schema": [],
                }
            ],
        }
    ]
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=True,
        roles_with_steps=roles,
        time_enabled=True,
        start_time="08:00",
        execution_data={
            "s1": {
                "started_at": "2026-05-15T08:02:00Z",
                "completed_at": "2026-05-15T08:33:00Z",
            },
        },
    )
    step = ctx["roles"][0]["steps"][0]
    assert step["actual_started_at"] == "2026-05-15T08:02:00Z"
    assert step["actual_completed_at"] == "2026-05-15T08:33:00Z"


def test_scheduled_time_per_step_flat():
    steps = [
        {"id": "s1", "name": "A", "duration_min": 10, "params": {}, "param_schema": []},
        {"id": "s2", "name": "B", "duration_min": 20, "params": {}, "param_schema": []},
    ]
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=False,
        flat_steps=steps,
        time_enabled=True,
        start_time="09:00",
    )
    assert ctx["steps"][0]["scheduled_at"] == "09:00"
    assert ctx["steps"][1]["scheduled_at"] == "09:10"


def test_role_timeline_does_not_corrupt_flat_steps():
    """Both ctx['steps'] and ctx['roles'][*]['steps'] should reflect their own
    timeline; mutating the role timeline must not corrupt the flat list."""
    roles = [
        {
            "role_name": "OpA",
            "process_name": "",
            "process_description": "",
            "steps": [
                {
                    "id": "s1",
                    "name": "A",
                    "duration_min": 30,
                    "params": {},
                    "param_schema": [],
                }
            ],
        },
        {
            "role_name": "OpB",
            "process_name": "",
            "process_description": "",
            "steps": [
                {
                    "id": "s2",
                    "name": "B",
                    "duration_min": 30,
                    "params": {},
                    "param_schema": [],
                }
            ],
        },
    ]
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=True,
        roles_with_steps=roles,
        flat_steps=[
            {
                "id": "s1",
                "name": "A",
                "duration_min": 30,
                "params": {},
                "param_schema": [],
            },
            {
                "id": "s2",
                "name": "B",
                "duration_min": 30,
                "params": {},
                "param_schema": [],
            },
        ],
        time_enabled=True,
        start_time="08:00",
    )
    # Each role restarts at start_time
    assert ctx["roles"][0]["steps"][0]["scheduled_at"] == "08:00"
    assert ctx["roles"][1]["steps"][0]["scheduled_at"] == "08:00"
    # Flat list continues globally
    assert ctx["steps"][0]["scheduled_at"] == "08:00"
    assert ctx["steps"][1]["scheduled_at"] == "08:30"
