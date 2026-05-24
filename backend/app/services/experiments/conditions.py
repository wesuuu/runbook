"""F-0043 — Python port of frontend computeConditions for PDF export.

Keep in lockstep with frontend/src/lib/experiments/conditions.ts. Parity is
locked by backend/tests/fixtures/conditions_parity.json — both this module
and the Vitest test consume it.

Equality key uses `json.dumps(value, sort_keys=True, default=str)` applied
after numeric coercion, NOT `repr()`. Python's `repr(7) == '7'` and
`repr(7.0) == '7.0'` would split trailing-zero floats from integers. Plain
`json.dumps` would also split them: `json.dumps(7) == "7"` but
`json.dumps(7.0) == "7.0"`. The fix is to coerce ints to float before dumping
so both become `"7.0"`. Booleans are exempt because `isinstance(True, int)` is
True in Python — they must be checked first.
"""

import json
from typing import Any


def _canonicalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    return value


def _eq_key(value: Any) -> str:
    """Canonical equality key matching frontend `JSON.stringify(value)`.

    Coerces int to float before serialization so that `7` and `7.0`
    produce the same key. bool is a subclass of int in Python, so it
    must be checked first to avoid coercing True -> 1.0.
    """
    def coerce(v: Any) -> Any:
        if isinstance(v, bool):  # must precede int check
            return v
        if isinstance(v, int):
            return float(v)
        if isinstance(v, dict):
            return {k: coerce(vv) for k, vv in v.items()}
        if isinstance(v, list):
            return [coerce(x) for x in v]
        return v

    return json.dumps(coerce(value), sort_keys=True, default=str)


def compute_conditions(runs: list[dict]) -> list[dict]:
    """Build the varied-param table from a list of runs (dicts)."""
    # Map of (nodeLabel, paramKey) -> {run_id: cell}
    per_key: dict[tuple[str, str], dict[str, dict]] = {}
    # Track every unit seen per key so we can flag conflicts.
    units_seen_per_key: dict[tuple[str, str], set[str]] = {}
    run_ids: list[str] = []

    for run in runs:
        run_id = run["id"]
        run_ids.append(run_id)
        nodes = (run.get("graph") or {}).get("nodes") or []
        for node in nodes:
            if node.get("type") != "unitOp":
                continue
            data = node.get("data") or {}
            label = data.get("label")
            params = data.get("params") or {}
            schema = (data.get("paramSchema") or {}).get("properties") or {}
            if not label:
                continue
            for k, v in params.items():
                key = (label, k)
                cell: dict[str, Any] = {"value": _canonicalize(v)}
                unit = schema.get(k, {}).get("unit") if isinstance(schema.get(k), dict) else None
                if unit:
                    cell["unit"] = unit
                    units_seen_per_key.setdefault(key, set()).add(unit)
                per_key.setdefault(key, {})[run_id] = cell

    rows: list[dict] = []
    for (label, k), per_run in per_key.items():
        filled = {rid: per_run.get(rid, {"value": None}) for rid in run_ids}
        units = units_seen_per_key.get((label, k), set())
        unit_conflict = len(units) > 1
        # If exactly one unit was observed, re-apply to cells missing it.
        if len(units) == 1:
            (only_unit,) = units
            for rid, cell in filled.items():
                if cell.get("value") is not None and "unit" not in cell:
                    cell["unit"] = only_unit
        values = {_eq_key(c["value"]) for c in filled.values()}
        row: dict[str, Any] = {
            "nodeLabel": label,
            "paramKey": k,
            "varied": len(values) > 1 or unit_conflict,
            "perRun": filled,
        }
        if unit_conflict:
            row["unitConflict"] = True
        rows.append(row)
    return rows
