"""Shared matching helpers for benchmark scoring.

Used by both the F-0058 protocol-import scorer and the F-0057 batch-record
scorer. Stays small and stateless by design — domain-specific scoring
lives in each benchmark's own scoring module.
"""

from __future__ import annotations

from difflib import SequenceMatcher


def fuzzy_ratio(a: str, b: str) -> float:
    """Case-insensitive fuzzy similarity ratio in [0.0, 1.0].

    Whitespace stripped from both ends. Two empty strings count as a
    perfect match (1.0); one empty and one non-empty is 0.0.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def align_by_name(
    expected: list[dict],
    actual: list[dict],
    name_key: str,
    threshold: float = 0.7,
) -> list[tuple[dict, dict | None]]:
    """Greedy best-match alignment by fuzzy ratio on a named field.

    Returns (expected_item, matched_actual_or_None) pairs in expected order.
    Each actual item matches at most one expected item. If the best
    available ratio is below `threshold`, the expected item is marked
    unmatched.
    """
    remaining = list(actual)
    out: list[tuple[dict, dict | None]] = []
    for exp in expected:
        exp_name = exp.get(name_key, "")
        best = None
        best_ratio = 0.0
        for act in remaining:
            ratio = fuzzy_ratio(exp_name, act.get(name_key, ""))
            if ratio > best_ratio:
                best_ratio = ratio
                best = act
        if best is not None and best_ratio >= threshold:
            out.append((exp, best))
            remaining.remove(best)
        else:
            out.append((exp, None))
    return out


def f1(n_matched: int, n_expected: int, n_actual: int) -> float:
    """F1 score from match counts.

    Empty expected AND empty actual → 1.0 (trivially perfect).
    Empty expected with non-empty actual → 0.0 (all hallucinations).
    """
    if n_expected == 0 and n_actual == 0:
        return 1.0
    recall = n_matched / n_expected if n_expected else 0.0
    precision = n_matched / n_actual if n_actual else 0.0
    denom = precision + recall
    return 2 * precision * recall / denom if denom > 0 else 0.0
