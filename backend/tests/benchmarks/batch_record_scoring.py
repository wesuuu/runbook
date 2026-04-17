"""Scoring for batch record import Run-output benchmark.

Compares the `execution_data + run_metadata` produced by the pipeline
against `expected_run.json` fixtures. One public entry point `score_run`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tests.benchmarks.matching import f1, fuzzy_ratio


_fuzzy_match = fuzzy_ratio


_UNIT_SYNONYMS: dict[str, str] = {
    "°c": "c", "c": "c", "celsius": "c",
    "μm": "um", "um": "um", "micron": "um", "microns": "um",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "l", "liter": "l", "liters": "l",
    "g": "g", "grams": "g",
    "mg": "mg", "milligrams": "mg",
    "psi": "psi", "bar": "bar", "rpm": "rpm",
    "min": "min", "minute": "min", "minutes": "min",
    "hr": "hr", "hour": "hr", "hours": "hr", "h": "hr",
}


def _numeric_equal(a, b) -> bool:
    try:
        af, bf = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if af == bf:
        return True
    abs_diff = abs(af - bf)
    # Small absolute tolerance (0.01) for very small numbers
    if abs_diff <= 0.01:
        return True
    # Relative tolerance varies by magnitude
    denom = max(abs(af), abs(bf))
    if denom == 0:
        return False
    # Stricter for small values (< 10): 0.3% tolerance
    if denom < 10:
        return abs_diff / denom <= 0.003
    # Relaxed for larger values (>= 10): 5% tolerance
    return abs_diff / denom <= 0.05


def _normalize_unit(u: str | None) -> str:
    if u is None:
        return ""
    return _UNIT_SYNONYMS.get(u.lower().strip(), u.lower().strip())


def _unit_equal(a: str | None, b: str | None) -> bool:
    return _normalize_unit(a) == _normalize_unit(b)


@dataclass
class RunScoreDetails:
    steps_expected: int = 0
    steps_found: int = 0
    steps_missed: list[str] = field(default_factory=list)
    steps_extra: list[str] = field(default_factory=list)
    param_value_mismatches: list[dict] = field(default_factory=list)
    param_unit_mismatches: list[dict] = field(default_factory=list)
    timestamps_missed: list[dict] = field(default_factory=list)
    signatures_missed: list[dict] = field(default_factory=list)
    deviations_missed: list[dict] = field(default_factory=list)
    na_mismatches: list[dict] = field(default_factory=list)
    notes_mismatches: list[dict] = field(default_factory=list)
    run_metadata_mismatches: list[dict] = field(default_factory=list)


@dataclass
class RunScores:
    fixture_name: str
    step_completeness: float = 0.0     # 20%
    param_accuracy: float = 0.0        # 25%
    timestamps: float = 0.0            # 15%
    signatures: float = 0.0            # 10%
    deviations: float = 0.0            # 10%
    na_correctness: float = 0.0        # 10%
    notes_preservation: float = 0.0    # 5%
    run_metadata: float = 0.0          # 5%
    details: RunScoreDetails = field(default_factory=RunScoreDetails)

    @property
    def overall(self) -> float:
        return (
            self.step_completeness * 0.20
            + self.param_accuracy * 0.25
            + self.timestamps * 0.15
            + self.signatures * 0.10
            + self.deviations * 0.10
            + self.na_correctness * 0.10
            + self.notes_preservation * 0.05
            + self.run_metadata * 0.05
        )

    @property
    def passed(self) -> bool:
        return self.overall >= 0.75

    def to_dict(self) -> dict:
        return {
            "fixture": self.fixture_name,
            "overall": round(self.overall, 3),
            "step_completeness": round(self.step_completeness, 3),
            "param_accuracy": round(self.param_accuracy, 3),
            "timestamps": round(self.timestamps, 3),
            "signatures": round(self.signatures, 3),
            "deviations": round(self.deviations, 3),
            "na_correctness": round(self.na_correctness, 3),
            "notes_preservation": round(self.notes_preservation, 3),
            "run_metadata": round(self.run_metadata, 3),
            "details": {
                "steps_expected": self.details.steps_expected,
                "steps_found": self.details.steps_found,
                "steps_missed": self.details.steps_missed,
                "steps_extra": self.details.steps_extra,
                "param_value_mismatches": self.details.param_value_mismatches,
                "param_unit_mismatches": self.details.param_unit_mismatches,
                "timestamps_missed": self.details.timestamps_missed,
                "signatures_missed": self.details.signatures_missed,
                "deviations_missed": self.details.deviations_missed,
                "na_mismatches": self.details.na_mismatches,
                "notes_mismatches": self.details.notes_mismatches,
                "run_metadata_mismatches": self.details.run_metadata_mismatches,
            },
        }


def score_run(
    actual_execution_data: dict,
    actual_run_metadata: dict,
    expected_run: dict,
    protocol_graph: dict,
    fixture_name: str = "",
) -> RunScores:
    """Score the pipeline's Run output against expected_run.json."""
    scores = RunScores(fixture_name=fixture_name)
    d = scores.details

    expected_ed = expected_run.get("execution_data", {})
    actual_ed = actual_execution_data

    d.steps_expected = len(expected_ed)
    d.steps_found = len(actual_ed)

    # ── 1. step_completeness (F1 over protocol_step_ids) ──
    expected_keys = set(expected_ed.keys())
    actual_keys = set(actual_ed.keys())
    matched_keys = expected_keys & actual_keys
    d.steps_missed = sorted(expected_keys - actual_keys)
    d.steps_extra = sorted(actual_keys - expected_keys)
    scores.step_completeness = f1(
        n_matched=len(matched_keys),
        n_expected=len(expected_keys),
        n_actual=len(actual_keys),
    )

    # ── 2. param_accuracy (per matched completed step, exact-key + value match) ──
    param_total = 0
    param_correct = 0
    for step_id in matched_keys:
        exp_step = expected_ed[step_id]
        act_step = actual_ed[step_id]
        if exp_step.get("status") != "completed":
            continue
        exp_results = exp_step.get("results", {}) or {}
        act_results = act_step.get("results", {}) or {}
        for key, exp_val in exp_results.items():
            param_total += 1
            if key not in act_results:
                d.param_value_mismatches.append({
                    "step": step_id, "key": key,
                    "expected": exp_val, "actual": None,
                })
                continue
            act_val = act_results[key]
            if isinstance(exp_val, (int, float)) and isinstance(act_val, (int, float)):
                if _numeric_equal(exp_val, act_val):
                    param_correct += 1
                else:
                    d.param_value_mismatches.append({
                        "step": step_id, "key": key,
                        "expected": exp_val, "actual": act_val,
                    })
            else:
                if str(exp_val).lower().strip() == str(act_val).lower().strip():
                    param_correct += 1
                else:
                    d.param_value_mismatches.append({
                        "step": step_id, "key": key,
                        "expected": exp_val, "actual": act_val,
                    })
    scores.param_accuracy = (
        param_correct / param_total if param_total > 0 else 1.0
    )

    # ── 3. na_correctness (per matched step, status must match) ──
    na_total = 0
    na_correct = 0
    for step_id in matched_keys:
        exp_status = expected_ed[step_id].get("status")
        act_status = actual_ed[step_id].get("status")
        if exp_status in ("completed", "na"):
            na_total += 1
            if exp_status == act_status:
                na_correct += 1
            else:
                d.na_mismatches.append({
                    "step": step_id,
                    "expected": exp_status,
                    "actual": act_status,
                })
    scores.na_correctness = (
        na_correct / na_total if na_total > 0 else 1.0
    )

    return scores
