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

    # ── 3. timestamps F1 over (step, label, value) ──
    exp_ts: list[tuple] = []
    for step_id, s in expected_ed.items():
        for t in s.get("timestamps", []) or []:
            exp_ts.append((step_id, t.get("label", ""), t.get("value", "")))
    act_ts: list[tuple] = []
    for step_id, s in actual_ed.items():
        for t in s.get("timestamps", []) or []:
            act_ts.append((step_id, t.get("label", ""), t.get("value", "")))
    if not exp_ts and not act_ts:
        scores.timestamps = 1.0
    elif not exp_ts:
        scores.timestamps = 0.0
    else:
        matched = 0
        remaining = list(act_ts)
        for exp in exp_ts:
            best = None
            best_r = 0.0
            for act in remaining:
                r = (
                    _fuzzy_match(exp[0], act[0]) * 0.5
                    + _fuzzy_match(exp[1], act[1]) * 0.25
                    + _fuzzy_match(exp[2], act[2]) * 0.25
                )
                if r > best_r:
                    best_r = r
                    best = act
            if best is not None and best_r >= 0.7:
                matched += 1
                remaining.remove(best)
            else:
                d.timestamps_missed.append({
                    "step": exp[0], "label": exp[1], "value": exp[2],
                })
        scores.timestamps = f1(
            n_matched=matched, n_expected=len(exp_ts), n_actual=len(act_ts),
        )

    # ── 4. signatures F1 over (step, initials, role) ──
    def _f1_tuples(exp_list, act_list, threshold=0.7):
        if not exp_list and not act_list:
            return 1.0, []
        if not exp_list:
            return 0.0, []
        matched, missed = 0, []
        remaining = list(act_list)
        for exp in exp_list:
            best, best_r = None, 0.0
            for act in remaining:
                r = sum(_fuzzy_match(e, a) for e, a in zip(exp, act)) / len(exp)
                if r > best_r:
                    best_r = r
                    best = act
            if best is not None and best_r >= threshold:
                matched += 1
                remaining.remove(best)
            else:
                missed.append(exp)
        return (
            f1(n_matched=matched, n_expected=len(exp_list), n_actual=len(act_list)),
            missed,
        )

    exp_sigs, act_sigs = [], []
    for step_id, s in expected_ed.items():
        for sig in s.get("signatures", []) or []:
            exp_sigs.append((step_id, sig.get("initials_or_name", ""), sig.get("role") or ""))
    for step_id, s in actual_ed.items():
        for sig in s.get("signatures", []) or []:
            act_sigs.append((step_id, sig.get("initials_or_name", ""), sig.get("role") or ""))
    scores.signatures, sig_missed = _f1_tuples(exp_sigs, act_sigs)
    d.signatures_missed.extend(
        {"step": m[0], "initials_or_name": m[1], "role": m[2]} for m in sig_missed
    )

    # ── 5. deviations F1 over (step, description) ──
    exp_devs, act_devs = [], []
    for step_id, s in expected_ed.items():
        for dv in s.get("deviations", []) or []:
            exp_devs.append((step_id, dv.get("description", "")))
    for step_id, s in actual_ed.items():
        for dv in s.get("deviations", []) or []:
            act_devs.append((step_id, dv.get("description", "")))
    scores.deviations, dev_missed = _f1_tuples(exp_devs, act_devs, threshold=0.6)
    d.deviations_missed.extend(
        {"step": m[0], "description": m[1]} for m in dev_missed
    )

    # ── 7. notes_preservation (avg fuzzy ratio per matched completed step) ──
    notes_scores: list[float] = []
    for step_id in matched_keys:
        exp_step = expected_ed[step_id]
        if exp_step.get("status") != "completed":
            continue
        exp_notes = exp_step.get("notes", "") or ""
        act_notes = actual_ed[step_id].get("notes", "") or ""
        if not exp_notes and not act_notes:
            continue
        ratio = _fuzzy_match(exp_notes, act_notes)
        notes_scores.append(ratio)
        if ratio < 0.7:
            d.notes_mismatches.append({
                "step": step_id, "expected": exp_notes, "actual": act_notes,
            })
    scores.notes_preservation = (
        sum(notes_scores) / len(notes_scores) if notes_scores else 1.0
    )

    # ── 8. run_metadata (run_name fuzzy ≥0.8) ──
    exp_name = expected_run.get("run_name", "") or ""
    act_name = actual_run_metadata.get("run_name", "") or ""
    if not exp_name and not act_name:
        scores.run_metadata = 1.0
    elif _fuzzy_match(exp_name, act_name) >= 0.8:
        scores.run_metadata = 1.0
    else:
        scores.run_metadata = 0.0
        d.run_metadata_mismatches.append({
            "field": "run_name", "expected": exp_name, "actual": act_name,
        })

    return scores
