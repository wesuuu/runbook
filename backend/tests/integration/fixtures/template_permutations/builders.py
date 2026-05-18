"""Shared types and helpers for permutation fixtures.

Each ``build_pN()`` returns a :class:`BuiltPermutation`:

- ``kwargs`` is the dict of keyword args passed to ``build_context()``.
- ``expected_on`` is a list of substrings that MUST appear in the rendered
  text.
- ``expected_off`` is a list of substrings that MUST NOT appear.
- ``renders_against`` is the tuple of template keys (``"sop"``,
  ``"batch_record"``) the permutation is configured to render against.
- ``context_overrides`` is an optional dict merged into the context after
  ``build_context()`` returns (e.g. to inject ``unapproved_warning``).
- ``per_template_expected_on`` / ``per_template_expected_off`` (optional)
  override ``expected_on`` / ``expected_off`` for a specific template key
  when one permutation renders against multiple templates with different
  surfaces. The base lists apply when no per-template entry exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BuiltPermutation:
    name: str
    kwargs: dict
    expected_on: list[str] = field(default_factory=list)
    expected_off: list[str] = field(default_factory=list)
    renders_against: tuple[str, ...] = ("sop", "batch_record")
    context_overrides: dict | None = None
    per_template_expected_on: dict[str, list[str]] = field(default_factory=dict)
    per_template_expected_off: dict[str, list[str]] = field(default_factory=dict)


# ---------- Shared step factory ----------

def _step(sid, name, *, duration=10, params=None, schema=None, equipment=None):
    """Build a step dict.

    ``schema`` should be a list of dicts with keys ``key``, ``label``,
    ``unit``, ``type`` — they are converted to the JSON-Schema
    ``{"properties": {...}}`` format expected by ``_get_editable_params``.
    """
    # Convert list-of-field-defs to {"properties": {key: {title, unit}}} format
    if schema:
        props = {}
        for field_def in schema:
            k = field_def["key"]
            props[k] = {
                "title": field_def.get("label", k),
                "unit": field_def.get("unit", ""),
            }
        param_schema = {"properties": props}
    else:
        param_schema = {}
    return {
        "id": sid,
        "name": name,
        "description": "",
        "duration_min": duration,
        "params": params or {},
        "param_schema": param_schema,
        "equipment": equipment or [],
    }


def _role(name, steps, *, process_name="", process_description=""):
    return {
        "role_name": name,
        "process_name": process_name,
        "process_description": process_description,
        "steps": steps,
    }


def _approval(actor_name, role, when, statement=None):
    return {
        "actor_name": actor_name,
        "actor_role": role,
        "approved_at": when,
        "signature_statement": statement,
        "signature_image": None,
    }


def _event(action, actor, when):
    return {"action": action, "actor_name": actor, "created_at": when}


# ---------- P1: Kitchen sink ----------

def build_p1() -> BuiltPermutation:
    roles = [
        _role("Operator", [
            _step("p1-s1", "Weigh media", duration=5,
                  params={"mass_g": 50.0},
                  schema=[{"key": "mass_g", "label": "Mass", "unit": "g", "type": "number"}],
                  equipment=[{"local_id": "E-001", "name": "Balance", "description": "Mettler XPE"}]),
            _step("p1-s2", "Mix buffer", duration=15,
                  params={"volume_L": 2.0, "rpm": 200},
                  schema=[{"key": "volume_L", "label": "Volume", "unit": "L", "type": "number"},
                          {"key": "rpm", "label": "RPM", "unit": "", "type": "number"}],
                  equipment=[{"local_id": "E-002", "name": "Magnetic Stirrer", "description": "IKA RT"}]),
            _step("p1-s3", "Seed bioreactor", duration=30,
                  params={"cell_density": 0.3e6},
                  schema=[{"key": "cell_density", "label": "Density", "unit": "cells/mL", "type": "number"}],
                  equipment=[{"local_id": "E-003", "name": "Bioreactor", "description": "Sartorius 5L"}]),
        ]),
        _role("Reviewer", [
            _step("p1-s4", "Verify pH", duration=10,
                  params={"ph": 7.2},
                  schema=[{"key": "ph", "label": "pH", "unit": "", "type": "number"}],
                  equipment=[{"local_id": "E-004", "name": "pH Probe", "description": "Mettler S400"}]),
        ]),
    ]
    return BuiltPermutation(
        name="P1_kitchen_sink",
        kwargs=dict(
            protocol_name="P1 — Kitchen Sink Cell Culture",
            protocol_description="End-to-end coverage of every template surface.",
            version_number=3,
            created_at="2026-05-15",
            project_name="Demo Project",
            organization_name="Trellis Bio",
            run_name="P1 Run",
            run_status="COMPLETED",
            started_at="2026-05-15T08:00:00Z",
            completed_at="2026-05-15T09:30:00Z",
            is_role_based=True,
            roles_with_steps=roles,
            time_enabled=True,
            start_time="08:00",
            doc_number="SOP-CC-001",
            effective_date="2026-01-01",
            supersedes_date="2025-06-01",
            purpose="Define the cell culture and harvest procedure.",
            scope="Applies to clone PD-7 in the 5L bioreactor.",
            references="ICH Q7; internal SOP-CORE-001",
            definitions="CIP = clean-in-place. PD = process development.",
            lot_number="LOT-2026-001",
            batch_number="BAT-7",
            # F-0086: lot row is now gated on produces_lot; the kitchen-sink
            # permutation exercises the "lot-producing run" branch.
            produces_lot=True,
            revision_history=[
                {"version_number": 1, "created_at": "2025-12-01",
                 "created_by": "Alice", "change_summary": "Initial release"},
                {"version_number": 2, "created_at": "2026-01-15",
                 "created_by": "Bob",   "change_summary": "Tightened acceptance"},
            ],
            user_map={"u-1": "Olivia Operator", "u-2": "Robin Reviewer"},
            execution_data={
                "p1-s1": {"started_at": "2026-05-15T08:02:00Z",
                          "completed_at": "2026-05-15T08:07:00Z",
                          "edited_by_user_id": "u-1",
                          "edited_at": "2026-05-15T08:08:00Z"},
                "p1-s2": {"started_at": "2026-05-15T08:10:00Z",
                          "completed_at": "2026-05-15T08:25:00Z"},
                "p1-s3": {"started_at": "2026-05-15T08:30:00Z",
                          "completed_at": "2026-05-15T09:00:00Z"},
                "p1-s4": {"started_at": "2026-05-15T09:05:00Z",
                          "completed_at": "2026-05-15T09:15:00Z",
                          "reviewed_by_user_id": "u-2",
                          "reviewed_at": "2026-05-15T09:20:00Z"},
            },
            notes=[
                {"content": "Buffer foamed unexpectedly", "flags": ["anomaly"],
                 "author_id": "u-1", "author_name": "Olivia", "created_at": "2026-05-15T08:11:00Z"},
                {"content": "Probe drift suspected", "flags": ["anomaly"],
                 "author_id": "u-2", "author_name": "Robin", "created_at": "2026-05-15T09:06:00Z"},
                {"content": "Routine handoff to next shift", "flags": [],
                 "author_id": "u-1", "author_name": "Olivia", "created_at": "2026-05-15T09:00:00Z"},
            ],
        ),
        expected_on=["Kitchen Sink"],
        expected_off=[],
        renders_against=("sop", "batch_record"),
        # P1 is the catalog-coverage kitchen-sink permutation; SOP and BR
        # each render a different subset of the populated fields, so the
        # per-template overrides describe what each side must surface.
        per_template_expected_on={
            "sop": [
                "Kitchen Sink", "SOP-CC-001",
                # Numbered headings from the GLP/bioreactor-style SOP layout
                "1.0 Purpose", "2.0 Scope", "3.0 Procedure",
                # Body text from the populated metadata fields
                "Define the cell culture", "Applies to clone PD-7",
                # Role subsection headers (3.1, 3.2 ...) — P1 has two roles
                "Operator", "Reviewer",
                # Step rows from the procedure table
                "Weigh media", "Mix buffer", "Verify pH",
            ],
            "batch_record": [
                "Kitchen Sink",
                # GLP-style numbered section headers
                "1. General Information",
                "2. Bill of Materials (BOM)",
                "3. Equipment Log",
                "4. Execution: Unit Operations",
                "5. Deviations and Process Comments",
                "6. Final Disposition & Signatures",
                # F-0086: lot row binds to lot_number and is gated on
                # produces_lot=True. The cell now surfaces the lot number,
                # not the run name.
                "Batch / Lot Number", "LOT-2026-001",
                # Notes appear in the Deviations section
                "Robin", "Olivia",
                # Step-execution table column captions
                "Verifier", "Operator",
                # Step rows from the execution table
                "Weigh media", "Mix buffer", "Verify pH",
            ],
        },
        per_template_expected_off={
            # SOP never renders run-execution or lot/batch fields, and the
            # GLP-style BR section headers are absent from SOP renders.
            "sop": [
                "Batch / Lot Number",
                "Bill of Materials",
                "Wet-Ink Sign-Off",
            ],
            "batch_record": [],
        },
    )


# ---------- P2: Minimal flat experiment ----------

def build_p2() -> BuiltPermutation:
    steps = [_step("p2-s1", "Pipette sample", duration=5),
             _step("p2-s2", "Read absorbance", duration=2)]
    return BuiltPermutation(
        name="P2_minimal",
        kwargs=dict(
            protocol_name="P2 — Minimal Experiment",
            project_name="Demo", organization_name="Trellis",
            is_role_based=False, flat_steps=steps,
        ),
        expected_on=["Minimal Experiment", "1.0 Purpose", "Pipette sample"],
        # Rendered against SOP only: the GLP-style BR-only sections / fields
        # must not appear in the SOP render.
        expected_off=[
            "Batch / Lot Number",
            "Bill of Materials",
            "Verifier",
            "Wet-Ink Sign-Off",
        ],
        renders_against=("sop",),
    )


# ---------- P3: Role-based, no time, with equipment ----------

def build_p3() -> BuiltPermutation:
    roles = [
        _role("Operator", [
            _step("p3-s1", "Harvest", duration=20,
                  equipment=[{"local_id": "E-010", "name": "Centrifuge", "description": "Beckman"}]),
        ]),
    ]
    return BuiltPermutation(
        name="P3_role_no_time",
        kwargs=dict(
            protocol_name="P3 — Harvest (no time)",
            project_name="Demo", organization_name="Trellis",
            is_role_based=True, roles_with_steps=roles,
            time_enabled=False,
        ),
        # The SOP layout does not surface per-step equipment names — assert
        # on what is actually rendered: the protocol name (which contains
        # "Harvest") and the always-present procedure heading.
        expected_on=["Harvest", "3.0 Procedure"],
        # SOP-only render: BR-only sections / fields must be absent.
        expected_off=[
            "Batch / Lot Number",
            "Bill of Materials",
            "Verifier",
            "Wet-Ink Sign-Off",
        ],
        renders_against=("sop",),
    )


# ---------- P4: Flat with time ----------

def build_p4() -> BuiltPermutation:
    steps = [_step("p4-s1", "Pre-warm", duration=10),
             _step("p4-s2", "Inoculate", duration=5)]
    return BuiltPermutation(
        name="P4_flat_with_time",
        kwargs=dict(
            protocol_name="P4 — Flat Timed",
            project_name="Demo", organization_name="Trellis",
            is_role_based=False, flat_steps=steps,
            time_enabled=True, start_time="08:00",
        ),
        # GLP-style BR no longer has a "Scheduled" column. Assert on the
        # protocol title plus always-present skeleton headings + the step
        # rows that actually render.
        expected_on=[
            "Flat Timed",
            "4. Execution: Unit Operations",
            "Pre-warm",
            "Inoculate",
        ],
        # SOP-style headings ("1.0 Purpose", "2.0 Scope") are absent from
        # BR renders — useful as cross-template negative checks.
        expected_off=["1.0 Purpose", "2.0 Scope", "Standard Operating Procedure"],
        renders_against=("batch_record",),
    )


# ---------- P5: Unapproved + deviations + reviewer ----------

def build_p5() -> BuiltPermutation:
    roles = [
        _role("Operator", [
            _step("p5-s1", "Adjust pH", duration=5,
                  equipment=[{"local_id": "E-020", "name": "pH Probe"}]),
            _step("p5-s2", "Sample", duration=5),
        ]),
    ]
    return BuiltPermutation(
        name="P5_unapproved_deviations",
        kwargs=dict(
            protocol_name="P5 — Unapproved Run with Deviations",
            project_name="Demo", organization_name="Trellis",
            is_role_based=True, roles_with_steps=roles,
            time_enabled=True, start_time="07:30",
            user_map={"u-3": "Sam Sampler"},
            execution_data={
                "p5-s1": {"reviewed_by_user_id": "u-3", "reviewed_at": "2026-05-15T07:45:00Z"},
            },
            notes=[
                {"content": "pH undershoot", "flags": ["anomaly"],
                 "author_id": "u-3", "author_name": "Sam", "created_at": "t1"},
                {"content": "Sample cloudy", "flags": ["anomaly"],
                 "author_id": "u-3", "author_name": "Sam", "created_at": "t2"},
                {"content": "Sensor recalibrated", "flags": ["anomaly"],
                 "author_id": "u-3", "author_name": "Sam", "created_at": "t3"},
            ],
        ),
        # "Unapproved" matches via the protocol title; the GLP BR layout
        # renders "Deviations and Process Comments" as a section heading
        # and "Lead Reviewer Sign-off" as a deviations-table column.
        expected_on=[
            "Unapproved",
            "Deviations and Process Comments",
            "Lead Reviewer",
            # The unapproved warning banner uses the en-dash em-dash
            # variant; assert on the substring that is locale-stable.
            "UNAPPROVED",
        ],
        expected_off=["1.0 Purpose", "Standard Operating Procedure"],
        renders_against=("batch_record",),
        # unapproved_warning is not set by build_context; inject it manually
        # so the template's conditional block renders the warning text.
        context_overrides={"unapproved_warning":
                           "Unapproved — this run lacks an approval signature."},
    )


# ---------- P6: Multi-event approval history ----------

def build_p6() -> BuiltPermutation:
    roles = [_role("Operator", [_step("p6-s1", "Final review", duration=5)])]
    return BuiltPermutation(
        name="P6_multi_approval",
        kwargs=dict(
            protocol_name="P6 — Multi-event Approval",
            project_name="Demo", organization_name="Trellis",
            is_role_based=True, roles_with_steps=roles,
            time_enabled=True, start_time="08:00",
            lot_number="LOT-2026-006",
            # F-0086: lot row is gated on produces_lot — enable it so the
            # Batch / Lot Number row renders with the lot number.
            produces_lot=True,
        ),
        # F-0086: lot row now binds to lot_number (not run_name) and is
        # only visible when produces_lot=True.
        expected_on=[
            "Multi-event Approval",
            "Batch / Lot Number",
            "LOT-2026-006",
            "6. Final Disposition & Signatures",
        ],
        expected_off=["1.0 Purpose", "Standard Operating Procedure"],
        renders_against=("batch_record",),
    )
