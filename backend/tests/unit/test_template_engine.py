"""Permanent tests for the docxtpl template engine.

Each test renders a template with specific fixture data, writes .docx
and .pdf artifacts to tests/artifacts/templates/ for manual inspection,
and asserts basic sanity (valid PDF, non-empty).

Fixture matrix covers: simple, role-based, process-based protocols,
and filled batch records (simple, roles, GMP edits, figures).
"""

from pathlib import Path

import pytest

from app.services.protocols.template_engine import (build_context,
                                                    render_to_docx,
                                                    render_to_pdf)

ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts" / "templates"
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "images"
SOP_TEMPLATE = Path("app/services/documents/templates/sop_default.docx")
BR_TEMPLATE = Path("app/services/documents/templates/batch_record_default.docx")


@pytest.fixture(autouse=True)
def ensure_artifacts_dir():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _write_artifact(name: str, docx_bytes: bytes | None, pdf_bytes: bytes):
    """Write artifacts for manual inspection."""
    if docx_bytes:
        (ARTIFACTS_DIR / f"{name}.docx").write_bytes(docx_bytes)
    (ARTIFACTS_DIR / f"{name}.pdf").write_bytes(pdf_bytes)


# ── Shared fixture data ──

SIMPLE_ROLES_WITH_STEPS = [
    {
        "role_name": "",
        "steps": [
            {
                "id": "s1",
                "name": "Buffer Preparation",
                "description": "Prepare {{volume}} mL of PBS buffer.",
                "params": {"volume": 500},
                "param_schema": {
                    "properties": {"volume": {"title": "Volume", "unit": "mL"}}
                },
                "duration_min": 30,
            },
            {
                "id": "s2",
                "name": "Cell Seeding",
                "description": "Seed cells at target density.",
                "params": {"density": 1e6},
                "param_schema": {
                    "properties": {
                        "density": {"title": "Seeding Density", "unit": "cells/mL"}
                    }
                },
                "duration_min": 15,
            },
        ],
    },
]

SIMPLE_FLAT_STEPS = [
    {
        "id": "s1",
        "name": "Buffer Preparation",
        "description": "Prepare {{volume}} mL of PBS buffer.",
        "role_name": "",
        "params": {"volume": 500},
        "param_schema": {"properties": {"volume": {"title": "Volume", "unit": "mL"}}},
        "duration_min": 30,
    },
    {
        "id": "s2",
        "name": "Cell Seeding",
        "description": "Seed cells at target density.",
        "role_name": "",
        "params": {"density": 1e6},
        "param_schema": {
            "properties": {"density": {"title": "Seeding Density", "unit": "cells/mL"}}
        },
        "duration_min": 15,
    },
]

ROLE_BASED_ROLES = [
    {
        "role_name": "Media Prep",
        "steps": [
            {
                "id": "s1",
                "name": "Weigh Reagents",
                "description": "Weigh NaCl and KCl.",
                "params": {"nacl_g": 8.0, "kcl_g": 0.2},
                "param_schema": {
                    "properties": {
                        "nacl_g": {"title": "NaCl", "unit": "g"},
                        "kcl_g": {"title": "KCl", "unit": "g"},
                    }
                },
                "duration_min": 10,
            },
            {
                "id": "s2",
                "name": "Dissolve",
                "description": "Add to {{volume}} mL water and stir.",
                "params": {"volume": 1000},
                "param_schema": {
                    "properties": {"volume": {"title": "Volume", "unit": "mL"}}
                },
                "duration_min": 15,
            },
        ],
    },
    {
        "role_name": "QC",
        "steps": [
            {
                "id": "s3",
                "name": "Measure pH",
                "description": "Measure and adjust pH.",
                "params": {"target_ph": 7.4},
                "param_schema": {"properties": {"target_ph": {"title": "Target pH"}}},
                "duration_min": 5,
            },
        ],
    },
]

ROLE_BASED_FLAT = [
    {
        "id": "s1",
        "name": "Weigh Reagents",
        "description": "Weigh NaCl and KCl.",
        "role_name": "Media Prep",
        "params": {"nacl_g": 8.0, "kcl_g": 0.2},
        "param_schema": {
            "properties": {
                "nacl_g": {"title": "NaCl", "unit": "g"},
                "kcl_g": {"title": "KCl", "unit": "g"},
            }
        },
        "duration_min": 10,
    },
    {
        "id": "s2",
        "name": "Dissolve",
        "description": "Add to {{volume}} mL water and stir.",
        "role_name": "Media Prep",
        "params": {"volume": 1000},
        "param_schema": {"properties": {"volume": {"title": "Volume", "unit": "mL"}}},
        "duration_min": 15,
    },
    {
        "id": "s3",
        "name": "Measure pH",
        "description": "Measure and adjust pH.",
        "role_name": "QC",
        "params": {"target_ph": 7.4},
        "param_schema": {"properties": {"target_ph": {"title": "Target pH"}}},
        "duration_min": 5,
    },
]

PROCESS_BASED_ROLES = [
    {
        "role_name": "",
        "process_name": "Preparation",
        "process_description": "Initial setup and reagent prep.",
        "steps": SIMPLE_ROLES_WITH_STEPS[0]["steps"],
    },
    {
        "role_name": "",
        "process_name": "Execution",
        "process_description": "Run the main experiment.",
        "steps": [
            {
                "id": "s3",
                "name": "Incubation",
                "description": "Incubate at {{temp}} degrees for {{hours}} hours.",
                "params": {"temp": 37, "hours": 24},
                "param_schema": {
                    "properties": {
                        "temp": {"title": "Temperature", "unit": "C"},
                        "hours": {"title": "Duration", "unit": "hours"},
                    }
                },
                "duration_min": 1440,
            },
        ],
    },
]

FILLED_EXECUTION_DATA = {
    "s1": {
        "status": "completed",
        "results": {"nacl_g": 8.01, "kcl_g": 0.2},
        "completed_by_user_id": "user-1",
        "completed_at": "2026-04-01T10:30:00Z",
    },
    "s2": {
        "status": "completed",
        "results": {"volume": 1000},
        "completed_by_user_id": "user-1",
        "completed_at": "2026-04-01T10:45:00Z",
    },
    "s3": {
        "status": "completed",
        "results": {"target_ph": 7.38},
        "completed_by_user_id": "user-2",
        "completed_at": "2026-04-01T11:15:00Z",
    },
}

EDITED_EXECUTION_DATA = {
    "s1": {
        **FILLED_EXECUTION_DATA["s1"],
        "original_results": {"nacl_g": 8.0, "kcl_g": 0.19},
        "edited_by_user_id": "user-1",
        "edited_at": "2026-04-01T12:00:00Z",
    },
    "s2": FILLED_EXECUTION_DATA["s2"],
    "s3": FILLED_EXECUTION_DATA["s3"],
}

USER_MAP = {
    "user-1": "Dr. Sarah Chen",
    "user-2": "James Wilson",
}

SAMPLE_NOTES = [
    {
        "content": "Observed slight turbidity after buffer prep.",
        "author_name": "Dr. Sarah Chen",
        "created_at": "2026-04-01T10:35:00Z",
        "flags": [],
        "run_status": "ACTIVE",
    },
    {
        "content": "ANOMALY: Cell viability below threshold at 85%.",
        "author_name": "Dr. Sarah Chen",
        "created_at": "2026-04-01T11:20:00Z",
        "flags": ["anomaly"],
        "run_status": "ACTIVE",
    },
]

SAMPLE_ATTACHMENTS = [
    {
        "filename": "test_figure_1.png",
        "content_type": "image/png",
        "step_id": "s1",
        "uploaded_at": "2026-04-01T10:32:00Z",
        "file_path": str(FIXTURES_DIR / "test_figure_1.png"),
    },
    {
        "filename": "test_figure_2.png",
        "content_type": "image/png",
        "step_id": "s2",
        "uploaded_at": "2026-04-01T10:46:00Z",
        "file_path": str(FIXTURES_DIR / "test_figure_2.png"),
    },
    {
        "filename": "test_figure_3.png",
        "content_type": "image/png",
        "step_id": "s3",
        "uploaded_at": "2026-04-01T11:16:00Z",
        "file_path": str(FIXTURES_DIR / "test_figure_3.png"),
    },
]


def _assert_valid_pdf(pdf_bytes: bytes):
    assert len(pdf_bytes) > 500, "PDF too small"
    assert pdf_bytes[:4] == b"%PDF", "Not a valid PDF"


# ── SOP Tests ──


def test_sop_simple():
    ctx, _ = build_context(
        protocol_name="Simple Buffer Protocol",
        protocol_description="A simple two-step buffer preparation protocol.",
        version_number=1,
        created_at="April 1, 2026",
        roles_with_steps=SIMPLE_ROLES_WITH_STEPS,
        flat_steps=SIMPLE_FLAT_STEPS,
        is_role_based=False,
    )
    docx = render_to_docx(SOP_TEMPLATE, ctx)
    pdf = render_to_pdf(SOP_TEMPLATE, ctx)
    _write_artifact("sop_simple", docx, pdf)
    _assert_valid_pdf(pdf)


def test_sop_role_based():
    ctx, _ = build_context(
        protocol_name="Multi-Role Buffer Protocol",
        protocol_description="Protocol with Media Prep and QC roles.",
        version_number=2,
        created_at="April 1, 2026",
        roles_with_steps=ROLE_BASED_ROLES,
        flat_steps=ROLE_BASED_FLAT,
        is_role_based=True,
    )
    docx = render_to_docx(SOP_TEMPLATE, ctx)
    pdf = render_to_pdf(SOP_TEMPLATE, ctx)
    _write_artifact("sop_role_based", docx, pdf)
    _assert_valid_pdf(pdf)


PROCESS_FLAT_STEPS = SIMPLE_FLAT_STEPS + [
    {
        "id": "s3",
        "name": "Incubation",
        "description": "Incubate at {{temp}} degrees for {{hours}} hours.",
        "role_name": "",
        "params": {"temp": 37, "hours": 24},
        "param_schema": {
            "properties": {
                "temp": {"title": "Temperature", "unit": "C"},
                "hours": {"title": "Duration", "unit": "hours"},
            }
        },
        "duration_min": 1440,
    },
]


def test_sop_process_based():
    ctx, _ = build_context(
        protocol_name="Process-Based Protocol",
        protocol_description="Protocol organized by process sections.",
        version_number=1,
        created_at="April 1, 2026",
        roles_with_steps=PROCESS_BASED_ROLES,
        flat_steps=PROCESS_FLAT_STEPS,
        is_role_based=False,
    )
    docx = render_to_docx(SOP_TEMPLATE, ctx)
    pdf = render_to_pdf(SOP_TEMPLATE, ctx)
    _write_artifact("sop_process_based", docx, pdf)
    _assert_valid_pdf(pdf)


TIME_COURSE_POINTS = [
    {
        "name": "Hour 0 (T=0) — Inoculation Sampling",
        "preamble": (
            "Reference time point. Sample drawn immediately after "
            "inoculation establishes baseline viability and metabolite "
            "concentration."
        ),
        "figure": {
            "caption": "Figure 1: Inoculation sampling port (post-CIP).",
            "description": (
                "Annotated photograph of the bioreactor sampling port "
                "showing the sterile septum and integrated luer fitting."
            ),
        },
        "actions": [
            {
                "time": "T=0 min",
                "action": (
                    "Aseptically draw 5 mL via sterile sampling port into "
                    "pre-labelled 15 mL conical."
                ),
                "output": "Sample S-0 logged in eBR; cap torque verified.",
            },
            {
                "time": "T+10 min",
                "action": (
                    "Perform trypan-blue viability count (Cellometer K2, "
                    "1:1 dilution)."
                ),
                "output": "Viable cell density (cells/mL); viability %.",
            },
            {
                "time": "T+15 min",
                "action": "Submit retained aliquot to in-process QC (pH, glucose).",
                "output": "pH, glucose (g/L) recorded; sample chain-of-custody signed.",
            },
        ],
    },
    {
        "name": "Hour 3 (T=3) — Foam & Growth Check",
        "preamble": (
            "Inspection only — no draw unless foam height exceeds the "
            "documented limit."
        ),
        "figure": {
            "caption": "Figure 2: Acceptable vs. excessive foam.",
            "description": (
                "Side-by-side comparison of acceptable headspace foam "
                "(<10 mm) and the rejection threshold."
            ),
        },
        "actions": [
            {
                "time": "T=3 h",
                "action": (
                    "Visually inspect headspace foam height; compare to "
                    "Figure 2."
                ),
                "output": "PASS / FAIL noted in eBR; foam height (mm).",
            },
            {
                "time": "T=3 h +5 min",
                "action": (
                    "If FAIL: add 0.5 mL sterile antifoam-C via dedicated "
                    "addition port and re-inspect."
                ),
                "output": "Antifoam lot, volume, and post-add foam height logged.",
            },
        ],
    },
    {
        "name": "Hour 6 (T=6) — Feed Initiation Sampling",
        "preamble": (
            "Sample drawn immediately prior to bolus feed addition; "
            "establishes the pre-feed metabolic profile."
        ),
        "figure": None,
        "actions": [
            {
                "time": "T=6 h",
                "action": (
                    "Aseptically draw 10 mL into pre-labelled tube; split "
                    "into viability and metabolite aliquots."
                ),
                "output": "Sample S-6 logged; aliquots routed to bench + QC.",
            },
            {
                "time": "T=6 h +20 min",
                "action": (
                    "Initiate bolus feed (Feed-A, 50 mL) via peristaltic "
                    "pump P-02."
                ),
                "output": "Feed start time, pump RPM, and totaliser reading.",
            },
        ],
    },
]


def test_sop_time_based():
    ctx, _ = build_context(
        protocol_name="Time-Course Bioreactor Sampling and Viability Analysis",
        version_number=2,
        doc_number="SOP-BR-014",
        effective_date="May 1, 2026",
        organization_name="Trellis Bioworks",
        project_name="CHO-K1 Fed-Batch Optimization",
        created_at="May 17, 2026",
        purpose=(
            "Standardise the time-course sampling and in-process viability "
            "analysis of CHO-K1 fed-batch cultures across the 2 L Sartorius "
            "Biostat platform so that inter-operator and inter-batch results "
            "are directly comparable."
        ),
        scope=(
            "Applies to all GLP fed-batch development runs performed in "
            "Suite 2B on the Biostat A 2 L vessels (BR-201 through BR-204). "
            "Does not cover seed-train shake-flask sampling."
        ),
        critical_requirement=(
            "All sampling MUST occur within ±5 min of the nominal time "
            "point. Deviations >5 min require an in-process deviation "
            "(IPD) report before the next time point."
        ),
        is_time_based=True,
        time_points=TIME_COURSE_POINTS,
    )
    docx = render_to_docx(SOP_TEMPLATE, ctx)
    pdf = render_to_pdf(SOP_TEMPLATE, ctx)
    _write_artifact("sop_time_based", docx, pdf)
    _assert_valid_pdf(pdf)


# ── Batch Record Tests ──


def test_batch_record_blank_simple():
    ctx, _ = build_context(
        protocol_name="Simple Buffer Protocol",
        run_name="Preview",
        version_number=1,
        created_at="April 1, 2026",
        roles_with_steps=SIMPLE_ROLES_WITH_STEPS,
        flat_steps=SIMPLE_FLAT_STEPS,
        is_role_based=False,
    )
    docx = render_to_docx(BR_TEMPLATE, ctx)
    pdf = render_to_pdf(BR_TEMPLATE, ctx)
    _write_artifact("batch_record_blank_simple", docx, pdf)
    _assert_valid_pdf(pdf)


def test_batch_record_blank_roles():
    ctx, _ = build_context(
        protocol_name="Multi-Role Buffer Protocol",
        run_name="Preview",
        version_number=2,
        created_at="April 1, 2026",
        roles_with_steps=ROLE_BASED_ROLES,
        flat_steps=ROLE_BASED_FLAT,
        is_role_based=True,
    )
    docx = render_to_docx(BR_TEMPLATE, ctx)
    pdf = render_to_pdf(BR_TEMPLATE, ctx)
    _write_artifact("batch_record_blank_roles", docx, pdf)
    _assert_valid_pdf(pdf)


def test_batch_record_filled_simple():
    ctx, _ = build_context(
        protocol_name="Multi-Role Buffer Protocol",
        run_name="Run-2026-001",
        run_status="COMPLETED",
        version_number=2,
        created_at="April 1, 2026",
        roles_with_steps=ROLE_BASED_ROLES,
        flat_steps=ROLE_BASED_FLAT,
        is_role_based=True,
        execution_data=FILLED_EXECUTION_DATA,
        user_map=USER_MAP,
        notes=SAMPLE_NOTES,
    )
    docx = render_to_docx(BR_TEMPLATE, ctx)
    pdf = render_to_pdf(BR_TEMPLATE, ctx)
    _write_artifact("batch_record_filled_simple", docx, pdf)
    _assert_valid_pdf(pdf)


def test_batch_record_filled_edited_gmp():
    """GMP audit trail — original values with edit markers."""
    ctx, _ = build_context(
        protocol_name="Multi-Role Buffer Protocol",
        run_name="Run-2026-002 (Edited)",
        run_status="EDITED",
        version_number=2,
        created_at="April 1, 2026",
        roles_with_steps=ROLE_BASED_ROLES,
        flat_steps=ROLE_BASED_FLAT,
        is_role_based=True,
        execution_data=EDITED_EXECUTION_DATA,
        user_map=USER_MAP,
        notes=[SAMPLE_NOTES[0]],
    )
    docx = render_to_docx(BR_TEMPLATE, ctx)
    pdf = render_to_pdf(BR_TEMPLATE, ctx)
    _write_artifact("batch_record_filled_edited_gmp", docx, pdf)
    _assert_valid_pdf(pdf)


def test_batch_record_filled_figures():
    """Batch record with embedded figure images."""
    ctx, _ = build_context(
        protocol_name="Multi-Role Buffer Protocol",
        run_name="Run-2026-003 (With Figures)",
        run_status="COMPLETED",
        version_number=2,
        created_at="April 1, 2026",
        roles_with_steps=ROLE_BASED_ROLES,
        flat_steps=ROLE_BASED_FLAT,
        is_role_based=True,
        execution_data=FILLED_EXECUTION_DATA,
        user_map=USER_MAP,
        notes=SAMPLE_NOTES,
        attachments=SAMPLE_ATTACHMENTS,
    )
    docx = render_to_docx(BR_TEMPLATE, ctx)
    pdf = render_to_pdf(BR_TEMPLATE, ctx)
    _write_artifact("batch_record_filled_figures", docx, pdf)
    _assert_valid_pdf(pdf)


# ── _render_template (QA-0007) ──

from app.services.documents.pdf_base import _render_template  # noqa: E402


def test_render_template_returns_unresolved_list_for_missing_keys():
    out, unresolved = _render_template(
        "Mix {{volume}} mL and stir {{rpm}}.",
        {"volume": 500},
    )
    assert out == "Mix 500 mL and stir {{rpm}}."
    assert unresolved == ["rpm"]


def test_render_template_resolves_hyphenated_equipment_token():
    out, unresolved = _render_template(
        "Set up the {{E-001_name}} ({{E-001_description}}).",
        {
            "E-001_name": "Sartorius Bioreactor",
            "E-001_description": "5L stirred-tank, single-use",
        },
    )
    assert out == "Set up the Sartorius Bioreactor (5L stirred-tank, single-use)."
    assert unresolved == []


def test_render_template_leaves_unresolved_hyphen_token_literal_and_lists_it():
    out, unresolved = _render_template(
        "Calibrate {{E-009_name}}.",
        {"unrelated": "x"},
    )
    assert out == "Calibrate {{E-009_name}}."
    assert unresolved == ["E-009_name"]


def test_render_template_deduplicates_unresolved_preserves_order():
    out, unresolved = _render_template(
        "{{b}} {{a}} {{b}} {{c}}",
        {},
    )
    assert out == "{{b}} {{a}} {{b}} {{c}}"
    assert unresolved == ["b", "a", "c"]


def test_render_template_handles_empty_params_dict():
    out, unresolved = _render_template("Plain text", None)
    assert out == "Plain text"
    assert unresolved == []


def test_build_context_merges_equipment_into_step_params():
    equipment_context = {
        "E-001_name": "Sartorius Bioreactor",
        "E-001_description": "5L stirred-tank, single-use",
    }
    flat_steps = [
        {
            "id": "n1",
            "name": "Setup",
            "description": (
                "Set up the {{E-001_name}} ({{E-001_description}}). "
                "Volume {{volume}} mL."
            ),
            "params": {"volume": 500},
            "param_schema": {},
            "duration_min": 10,
            "role_name": "Op",
        }
    ]

    ctx, unresolved = build_context(
        protocol_name="P",
        flat_steps=flat_steps,
        is_role_based=False,
        equipment_context=equipment_context,
    )

    step_desc = ctx["steps"][0]["description"]
    assert "Sartorius Bioreactor" in step_desc
    assert "5L stirred-tank" in step_desc
    assert "500" in step_desc
    assert unresolved == []


def test_build_context_aggregates_unresolved_tokens_across_steps():
    flat_steps = [
        {
            "id": "n1",
            "name": "Step 1",
            "description": "Use {{E-999_name}} and {{missing_param}}.",
            "params": {"volume": 1},
            "param_schema": {},
            "duration_min": 1,
            "role_name": "",
        },
        {
            "id": "n2",
            "name": "Step 2",
            "description": "Also {{E-999_name}}.",
            "params": {},
            "param_schema": {},
            "duration_min": 1,
            "role_name": "",
        },
    ]
    _, unresolved = build_context(
        protocol_name="P",
        flat_steps=flat_steps,
        is_role_based=False,
        equipment_context={},
    )
    assert sorted(unresolved) == sorted(["E-999_name", "missing_param"])
