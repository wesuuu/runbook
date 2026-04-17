"""Scoring utilities for protocol import benchmarks.

Compares an actual ProtocolImportProposal (or equivalent dict) against
an expected.json fixture and produces per-dimension scores with detailed
breakdowns for debugging.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from tests.benchmarks.matching import align_by_name, f1, fuzzy_ratio


@dataclass
class ScoreDetails:
    """Granular breakdown for debugging failures."""

    steps_expected: int = 0
    steps_found: int = 0
    steps_missed: list[str] = field(default_factory=list)
    steps_extra: list[str] = field(default_factory=list)
    catalog_mismatches: list[dict] = field(default_factory=list)
    is_new_mismatches: list[dict] = field(default_factory=list)
    params_missed: list[dict] = field(default_factory=list)
    roles_missed: list[str] = field(default_factory=list)
    roles_extra: list[str] = field(default_factory=list)


@dataclass
class BenchmarkScores:
    """Per-dimension scores and overall weighted score."""

    fixture_name: str
    step_detection: float = 0.0
    catalog_matching: float = 0.0
    new_unit_op_detection: float = 0.0
    param_extraction: float = 0.0
    role_extraction: float = 0.0
    details: ScoreDetails = field(default_factory=ScoreDetails)

    @property
    def overall(self) -> float:
        return (
            self.step_detection * 0.30
            + self.catalog_matching * 0.25
            + self.new_unit_op_detection * 0.20
            + self.param_extraction * 0.15
            + self.role_extraction * 0.10
        )

    @property
    def passed(self) -> bool:
        return self.overall >= 0.75

    def to_dict(self) -> dict:
        return {
            "fixture": self.fixture_name,
            "overall": round(self.overall, 3),
            "step_detection": round(self.step_detection, 3),
            "catalog_matching": round(self.catalog_matching, 3),
            "new_unit_op_detection": round(self.new_unit_op_detection, 3),
            "param_extraction": round(self.param_extraction, 3),
            "role_extraction": round(self.role_extraction, 3),
            "details": {
                "steps_expected": self.details.steps_expected,
                "steps_found": self.details.steps_found,
                "steps_missed": self.details.steps_missed,
                "steps_extra": self.details.steps_extra,
                "catalog_mismatches": self.details.catalog_mismatches,
                "is_new_mismatches": self.details.is_new_mismatches,
                "params_missed": self.details.params_missed,
                "roles_missed": self.details.roles_missed,
                "roles_extra": self.details.roles_extra,
            },
        }


def _match_steps(
    expected_steps: list[dict], actual_steps: list[dict]
) -> list[tuple[dict, dict | None]]:
    """Match expected steps to actual steps by fuzzy name similarity.

    Thin wrapper over `matching.align_by_name` preserving the F-0058 call
    signature — expected/actual dicts keyed by "name".
    """
    return align_by_name(expected_steps, actual_steps, "name", threshold=0.7)


def score_proposal(
    actual: dict,
    expected: dict,
    fixture_name: str = "",
) -> BenchmarkScores:
    """Score an actual proposal (or its dict form) against expected.json.

    Args:
        actual: Dict with keys like {"steps": [...], "protocol_name": ...}.
                Each step has: name, category, matched_unit_op_name,
                is_new, params, role.
        expected: Loaded expected.json with same structure.
        fixture_name: Name for reporting.

    Returns:
        BenchmarkScores with per-dimension scores and breakdown details.
    """
    scores = BenchmarkScores(fixture_name=fixture_name)
    details = scores.details

    expected_steps = expected.get("steps", [])
    actual_steps = actual.get("steps", [])
    details.steps_expected = len(expected_steps)
    details.steps_found = len(actual_steps)

    # -- 1. Step Detection (F1 of precision + recall) --
    step_matches = _match_steps(expected_steps, actual_steps)
    matched_expected = [exp for exp, act in step_matches if act is not None]
    unmatched_expected = [exp for exp, act in step_matches if act is None]
    details.steps_missed = [s["name"] for s in unmatched_expected]

    # Find extra actual steps (not matched to any expected)
    matched_actual_names = {
        act["name"] for _, act in step_matches if act is not None
    }
    details.steps_extra = [
        s.get("name", "?") for s in actual_steps
        if s.get("name", "?") not in matched_actual_names
    ]

    scores.step_detection = f1(
        n_matched=len(matched_expected),
        n_expected=len(expected_steps),
        n_actual=len(actual_steps),
    )

    # -- 2. Catalog Matching --
    catalog_total = 0
    catalog_correct = 0
    for exp, act in step_matches:
        exp_match = exp.get("matched_unit_op_name")
        if exp_match is not None:  # expected to match something
            catalog_total += 1
            if act:
                act_match = act.get("matched_unit_op_name")
                if act_match and act_match.lower() == exp_match.lower():
                    catalog_correct += 1
                else:
                    details.catalog_mismatches.append({
                        "step": exp["name"],
                        "expected": exp_match,
                        "actual": act.get("matched_unit_op_name") if act else None,
                    })
            else:
                details.catalog_mismatches.append({
                    "step": exp["name"],
                    "expected": exp_match,
                    "actual": None,
                })

    scores.catalog_matching = (
        catalog_correct / catalog_total if catalog_total > 0 else 1.0
    )

    # -- 3. New Unit Op Detection --
    is_new_total = 0
    is_new_correct = 0
    for exp, act in step_matches:
        if act is not None:
            is_new_total += 1
            exp_is_new = exp.get("is_new", False)
            act_is_new = act.get("is_new", False)
            if exp_is_new == act_is_new:
                is_new_correct += 1
            else:
                details.is_new_mismatches.append({
                    "step": exp["name"],
                    "expected_is_new": exp_is_new,
                    "actual_is_new": act_is_new,
                })

    scores.new_unit_op_detection = (
        is_new_correct / is_new_total if is_new_total > 0 else 1.0
    )

    # -- 4. Parameter Extraction --
    param_total = 0
    param_correct = 0
    for exp, act in step_matches:
        exp_params = exp.get("expected_params", {})
        if not exp_params or act is None:
            continue
        act_params = act.get("params", {})
        for key, exp_val in exp_params.items():
            param_total += 1
            # Look for key in actual params (case-insensitive key match)
            act_val = None
            for ak, av in act_params.items():
                if ak.lower() == key.lower():
                    act_val = av
                    break

            if act_val is None:
                details.params_missed.append({
                    "step": exp["name"],
                    "param": key,
                    "expected": exp_val,
                    "actual": None,
                })
                continue

            # Compare values
            if _param_values_match(exp_val, act_val):
                param_correct += 1
            else:
                details.params_missed.append({
                    "step": exp["name"],
                    "param": key,
                    "expected": exp_val,
                    "actual": act_val,
                })

    scores.param_extraction = (
        param_correct / param_total if param_total > 0 else 1.0
    )

    # -- 5. Role Extraction --
    expected_roles = {r.lower() for r in expected.get("expected_roles", [])}
    actual_roles = {
        s.get("role", "").lower()
        for s in actual_steps
        if s.get("role")
    }
    if expected_roles or actual_roles:
        intersection = expected_roles & actual_roles
        union = expected_roles | actual_roles
        scores.role_extraction = len(intersection) / len(union) if union else 1.0
        details.roles_missed = [r for r in expected_roles if r not in actual_roles]
        details.roles_extra = [r for r in actual_roles if r not in expected_roles]
    else:
        scores.role_extraction = 1.0

    return scores


def _param_values_match(expected, actual) -> bool:
    """Compare param values with tolerance.

    - Numbers: within 20% tolerance
    - Strings: case-insensitive substring match
    - Booleans: exact match
    """
    if isinstance(expected, bool):
        return expected == actual

    if isinstance(expected, (int, float)):
        try:
            actual_num = float(actual)
        except (TypeError, ValueError):
            return False
        if expected == 0:
            return actual_num == 0
        return abs(actual_num - expected) / abs(expected) <= 0.2

    if isinstance(expected, str):
        if actual is None:
            return False
        return expected.lower() in str(actual).lower()

    return expected == actual


def print_score_report(scores: BenchmarkScores) -> None:
    """Print a formatted score table for a single fixture."""
    status = "PASS" if scores.passed else "FAIL"
    d = scores.details

    print()
    print(f"{'=' * 65}")
    print(f"  {scores.fixture_name:<45} {status} {scores.overall:.0%}")
    print(f"{'=' * 65}")
    print(f"  {'Dimension':<22} {'Score':>6}  Detail")
    print(f"  {'-' * 60}")
    print(
        f"  {'Step Detection':<22} {scores.step_detection:>5.2f}  "
        f"{d.steps_found}/{d.steps_expected} found, "
        f"{len(d.steps_extra)} extra"
    )
    print(
        f"  {'Catalog Matching':<22} {scores.catalog_matching:>5.2f}  "
        f"{len(d.catalog_mismatches)} mismatches"
    )
    print(
        f"  {'New Unit Op Detect':<22} {scores.new_unit_op_detection:>5.2f}  "
        f"{len(d.is_new_mismatches)} wrong"
    )
    print(
        f"  {'Param Extraction':<22} {scores.param_extraction:>5.2f}  "
        f"{len(d.params_missed)} missed"
    )
    print(
        f"  {'Role Extraction':<22} {scores.role_extraction:>5.2f}  "
        f"missed={d.roles_missed}, extra={d.roles_extra}"
    )
    print(f"  {'-' * 60}")
    print(f"  {'Overall (weighted)':<22} {scores.overall:>5.2f}  threshold: 0.75")
    print(f"{'=' * 65}")

    # Print missed details if any
    if d.steps_missed:
        print(f"  Steps missed: {d.steps_missed}")
    if d.catalog_mismatches:
        print(f"  Catalog mismatches: {json.dumps(d.catalog_mismatches, indent=4)}")
    if d.params_missed:
        print(f"  Params missed: {json.dumps(d.params_missed, indent=4)}")
    print()


def print_summary_table(all_scores: list[BenchmarkScores]) -> None:
    """Print aggregate summary table across all fixtures."""
    print()
    print(f"{'=' * 85}")
    print(f"  BENCHMARK SUMMARY")
    print(f"{'=' * 85}")
    print(
        f"  {'Fixture':<30} {'Overall':>7} {'Steps':>7} {'Match':>7} "
        f"{'NewOp':>7} {'Param':>7} {'Role':>7} {'Status':>7}"
    )
    print(f"  {'-' * 80}")
    for s in all_scores:
        status = "PASS" if s.passed else "FAIL"
        print(
            f"  {s.fixture_name:<30} {s.overall:>6.0%} "
            f"{s.step_detection:>6.0%} {s.catalog_matching:>6.0%} "
            f"{s.new_unit_op_detection:>6.0%} {s.param_extraction:>6.0%} "
            f"{s.role_extraction:>6.0%} {status:>7}"
        )
    print(f"  {'-' * 80}")

    # Averages
    n = len(all_scores) or 1
    print(
        f"  {'AVERAGE':<30} "
        f"{sum(s.overall for s in all_scores) / n:>6.0%} "
        f"{sum(s.step_detection for s in all_scores) / n:>6.0%} "
        f"{sum(s.catalog_matching for s in all_scores) / n:>6.0%} "
        f"{sum(s.new_unit_op_detection for s in all_scores) / n:>6.0%} "
        f"{sum(s.param_extraction for s in all_scores) / n:>6.0%} "
        f"{sum(s.role_extraction for s in all_scores) / n:>6.0%}"
    )
    passed = sum(1 for s in all_scores if s.passed)
    print(f"  {passed}/{len(all_scores)} fixtures passed")
    print(f"{'=' * 85}")
    print()
