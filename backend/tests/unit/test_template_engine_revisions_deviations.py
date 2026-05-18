"""QA-0008: revision_history, deviations, reviewer_enabled."""

import pytest

from app.services.protocols.template_engine import build_context


def test_revision_history_empty_by_default():
    ctx, _ = build_context(protocol_name="P")
    assert ctx["revision_history"] == []


def test_revision_history_passes_through():
    history = [
        {
            "version_number": 1,
            "created_at": "2026-01-01",
            "created_by": "Alice",
            "change_summary": "initial",
        },
        {
            "version_number": 2,
            "created_at": "2026-02-01",
            "created_by": "Bob",
            "change_summary": "tweak",
        },
    ]
    ctx, _ = build_context(
        protocol_name="P",
        revision_history=history,
    )
    assert ctx["revision_history"] == history


def test_deviations_filters_anomaly_notes():
    notes = [
        {
            "content": "ok",
            "flags": [],
            "author_id": "u",
            "author_name": "A",
            "created_at": "t1",
        },
        {
            "content": "weird color",
            "flags": ["anomaly"],
            "author_id": "u",
            "author_name": "A",
            "created_at": "t2",
        },
        {
            "content": "pH off",
            "flags": ["anomaly", "deviation"],
            "author_id": "u",
            "author_name": "A",
            "created_at": "t3",
        },
    ]
    ctx, _ = build_context(protocol_name="P", notes=notes)
    assert len(ctx["deviations"]) == 2
    assert all("anomaly" in n["flags"] for n in ctx["deviations"])


def test_reviewer_enabled_false_when_no_step_reviewed():
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
    assert ctx["reviewer_enabled"] is False


def test_reviewer_enabled_true_when_any_step_reviewed():
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
    )
    assert ctx["reviewer_enabled"] is True
