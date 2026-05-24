"""F-0043 — Python port of computeConditions matches frontend output."""

import json
from pathlib import Path

import pytest

from app.services.experiments.conditions import compute_conditions

FIXTURE = Path(__file__).parents[3] / "fixtures" / "conditions_parity.json"


@pytest.mark.parametrize(
    "scenario",
    json.loads(FIXTURE.read_text())["scenarios"],
    ids=lambda s: s["name"],
)
def test_parity(scenario):
    actual = compute_conditions(scenario["runs"])
    # Normalize to a comparable shape.
    actual_norm = []
    for row in actual:
        norm: dict = {
            "nodeLabel": row["nodeLabel"],
            "paramKey": row["paramKey"],
            "varied": row["varied"],
            "perRun": row["perRun"],
        }
        if row.get("unitConflict"):
            norm["unitConflict"] = True
        actual_norm.append(norm)
    assert actual_norm == scenario["expected"]
