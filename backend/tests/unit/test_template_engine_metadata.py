"""Metadata pass-throughs + responsibilities matrix in build_context."""

import pytest

from app.services.protocols.template_engine import build_context


def test_protocol_metadata_pass_through():
    ctx, _ = build_context(
        protocol_name="P",
        doc_number="SOP-0001",
        effective_date="2026-01-01",
        supersedes_date="2025-01-01",
        purpose="X",
        scope="Y",
        references="Z",
        definitions="D",
    )
    assert ctx["doc_number"] == "SOP-0001"
    assert ctx["effective_date"] == "2026-01-01"
    assert ctx["supersedes_date"] == "2025-01-01"
    assert ctx["purpose"] == "X"
    assert ctx["scope"] == "Y"
    assert ctx["references"] == "Z"
    assert ctx["definitions"] == "D"


def test_run_metadata_pass_through():
    ctx, _ = build_context(
        protocol_name="P",
        lot_number="LOT-1",
        batch_number="BAT-2",
    )
    assert ctx["lot_number"] == "LOT-1"
    assert ctx["batch_number"] == "BAT-2"


def test_metadata_defaults_empty_strings():
    ctx, _ = build_context(protocol_name="P")
    for k in (
        "doc_number",
        "effective_date",
        "supersedes_date",
        "purpose",
        "scope",
        "references",
        "definitions",
        "lot_number",
        "batch_number",
    ):
        assert ctx[k] == "", f"{k} not empty"


def test_responsibilities_from_roles():
    roles = [
        {
            "role_name": "Operator",
            "process_name": "Prep",
            "process_description": "",
            "steps": [
                {
                    "id": "s1",
                    "name": "Weigh",
                    "duration_min": 0,
                    "params": {},
                    "param_schema": [],
                },
                {
                    "id": "s2",
                    "name": "Mix",
                    "duration_min": 0,
                    "params": {},
                    "param_schema": [],
                },
            ],
        },
        {
            "role_name": "Reviewer",
            "process_name": "QC",
            "process_description": "",
            "steps": [
                {
                    "id": "s3",
                    "name": "Check",
                    "duration_min": 0,
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
    )
    resp = ctx["responsibilities"]
    assert len(resp) == 2
    assert resp[0]["role_name"] == "Operator"
    assert "Weigh" in resp[0]["step_summary"] and "Mix" in resp[0]["step_summary"]
    assert resp[1]["role_name"] == "Reviewer"
    assert "Check" in resp[1]["step_summary"]


def test_responsibilities_empty_when_not_role_based():
    ctx, _ = build_context(
        protocol_name="P",
        is_role_based=False,
        flat_steps=[
            {
                "id": "s",
                "name": "A",
                "duration_min": 0,
                "params": {},
                "param_schema": [],
            }
        ],
    )
    assert ctx["responsibilities"] == []
