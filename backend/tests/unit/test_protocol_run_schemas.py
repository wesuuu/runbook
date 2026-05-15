"""Unit tests for QA-0008 schema additions."""

from datetime import date

from app.schemas.science import (ProtocolCreate, ProtocolResponse,
                                 ProtocolUpdate, RunCreate, RunResponse,
                                 RunUpdate)


def test_protocol_create_accepts_gxp_fields():
    p = ProtocolCreate(
        name="N",
        graph={},
        doc_number="SOP-0001",
        effective_date=date(2026, 1, 1),
        supersedes_date=date(2025, 1, 1),
        purpose="P",
        scope="S",
        references="R",
        definitions="D",
    )
    assert p.doc_number == "SOP-0001"
    assert p.purpose == "P"


def test_protocol_update_accepts_gxp_fields():
    p = ProtocolUpdate(purpose="new")
    assert p.purpose == "new"


def test_run_create_accepts_lot_and_batch():
    r = RunCreate(
        name="R",
        project_id="00000000-0000-0000-0000-000000000001",
        lot_number="LOT-001",
        batch_number="BAT-1",
    )
    assert r.lot_number == "LOT-001"
    assert r.batch_number == "BAT-1"


def test_run_update_accepts_lot_and_batch():
    r = RunUpdate(lot_number="X")
    assert r.lot_number == "X"


def test_run_response_carries_lot_and_batch_when_set():
    fields = RunResponse.model_fields
    assert "lot_number" in fields
    assert "batch_number" in fields


def test_protocol_response_carries_gxp_fields():
    fields = ProtocolResponse.model_fields
    for k in (
        "doc_number",
        "effective_date",
        "supersedes_date",
        "purpose",
        "scope",
        "references",
        "definitions",
    ):
        assert k in fields, f"missing {k}"
