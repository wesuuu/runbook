"""Per-step reviewer initials surface on build_context."""

import pytest

from app.services.protocols.template_engine import build_context


def test_reviewer_initials_populated_from_execution_data():
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
                }
            ],
        }
    ]
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=True,
        roles_with_steps=roles,
        execution_data={
            "s1": {"reviewed_by_user_id": "u-2", "reviewed_at": "2026-05-15T09:00:00Z"}
        },
        user_map={"u-2": "Bob Reviewer"},
    )
    step = ctx["roles"][0]["steps"][0]
    assert step["reviewer_initials"] == "BR"
    assert step["reviewed_at"] == "2026-05-15T09:00:00Z"
    assert step["_reviewer_user_id"] == "u-2"
    assert step["_reviewer_name"] == "Bob Reviewer"


def test_reviewer_initials_empty_when_not_reviewed():
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
                }
            ],
        }
    ]
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=True,
        roles_with_steps=roles,
    )
    step = ctx["roles"][0]["steps"][0]
    assert step["reviewer_initials"] == ""
