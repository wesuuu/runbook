"""Equipment summary + per-step equipment in build_context."""

from app.services.protocols.template_engine import build_context


def test_equipment_summary_empty_when_no_equipment():
    ctx, _ = build_context(protocol_name="P")
    assert ctx["equipment_summary"] == []


def test_equipment_summary_unique_by_local_id():
    roles = [
        {
            "role_name": "Op",
            "process_name": "",
            "process_description": "",
            "steps": [
                {
                    "id": "s1",
                    "name": "A",
                    "duration_min": 0,
                    "params": {},
                    "param_schema": [],
                    "equipment": [
                        {"local_id": "E-001", "name": "Bioreactor", "description": "5L"}
                    ],
                },
                {
                    "id": "s2",
                    "name": "B",
                    "duration_min": 0,
                    "params": {},
                    "param_schema": [],
                    "equipment": [
                        {
                            "local_id": "E-001",
                            "name": "Bioreactor",
                            "description": "5L",
                        },
                        {
                            "local_id": "E-002",
                            "name": "Pump",
                            "description": "Peristaltic",
                        },
                    ],
                },
            ],
        }
    ]
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=True,
        roles_with_steps=roles,
    )
    summary = ctx["equipment_summary"]
    local_ids = [e["local_id"] for e in summary]
    assert local_ids == ["E-001", "E-002"]
    assert summary[0]["name"] == "Bioreactor"


def test_per_step_equipment_propagates():
    roles = [
        {
            "role_name": "Op",
            "process_name": "",
            "process_description": "",
            "steps": [
                {
                    "id": "s1",
                    "name": "A",
                    "duration_min": 0,
                    "params": {},
                    "param_schema": [],
                    "equipment": [{"local_id": "E-001", "name": "Bioreactor"}],
                },
            ],
        }
    ]
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=True,
        roles_with_steps=roles,
    )
    step = ctx["roles"][0]["steps"][0]
    assert step["equipment"] == [{"local_id": "E-001", "name": "Bioreactor"}]
