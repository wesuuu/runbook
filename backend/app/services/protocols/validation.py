"""Validate a Protocol graph against structural and quality rules.

Pure function — no DB, no LLM. Callers fetch the graph + unit-op catalog
and pass them in. Used by the chat agent's `validate_protocol` tool to
self-check work after `create_protocol`, and reusable from any future
REST endpoint or background job.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.science import UnitOpDefinition

Severity = str  # "error" | "warning"


class ValidationIssue(BaseModel):
    severity: Severity
    code: str
    message: str
    node_id: str | None = None


class ValidationResult(BaseModel):
    ok: bool
    issues: list[ValidationIssue]


_PLACEHOLDER_DESCRIPTIONS = {"", "todo", "tbd", "n/a", "placeholder"}


def validate_protocol_graph(
    graph: dict[str, Any],
    unit_ops: list[UnitOpDefinition],
) -> ValidationResult:
    """Check a graph for structural and quality problems.

    Args:
        graph: The Protocol.graph JSONB.
        unit_ops: Org-visible UnitOpDefinitions for resolving `unitOpId`.

    Returns:
        ValidationResult — `ok=False` if any issue has severity="error".
    """
    issues: list[ValidationIssue] = []
    nodes: list[dict[str, Any]] = list(graph.get("nodes", []))
    edges: list[dict[str, Any]] = list(graph.get("edges", []))

    process_starts = [n for n in nodes if n.get("type") == "processStart"]
    unit_op_nodes = [n for n in nodes if n.get("type") == "unitOp"]

    if not process_starts:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_process_start",
                message=(
                    "Protocol has no Process Start node. Every protocol must "
                    "begin with one."
                ),
            )
        )

    component_starts = _process_starts_per_component(nodes, edges, process_starts)
    for component_idx, count in enumerate(component_starts):
        if count > 1:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="multiple_process_starts",
                    message=(
                        f"Connected component {component_idx} has {count} "
                        "Process Start nodes; expected exactly 1."
                    ),
                )
            )

    unit_op_ids = {str(op.id) for op in unit_ops}
    incoming_targets = {e.get("target") for e in edges}

    for n in unit_op_nodes:
        node_id = n.get("id") or "<unknown>"
        data = n.get("data") or {}
        label = data.get("label") or "<unnamed>"

        unit_op_id = data.get("unitOpId")
        if unit_op_id and str(unit_op_id) not in unit_op_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unknown_unit_op_id",
                    message=(
                        f"Step '{label}' references unitOpId={unit_op_id} which "
                        "does not exist in the unit-op catalog."
                    ),
                    node_id=node_id,
                )
            )

        param_schema = data.get("paramSchema") or {}
        if not param_schema.get("properties"):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="empty_param_schema",
                    message=(
                        f"Step '{label}' has no parameter schema. Scientists "
                        "won't be able to set per-run values."
                    ),
                    node_id=node_id,
                )
            )

        description = (data.get("description") or "").strip().lower()
        if description in _PLACEHOLDER_DESCRIPTIONS:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="missing_description",
                    message=(
                        f"Step '{label}' has no description. Add instructions "
                        "the technician should follow."
                    ),
                    node_id=node_id,
                )
            )

        if not unit_op_id and (data.get("category") or "").lower() in {"", "general"}:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="placeholder_category",
                    message=(
                        f"Step '{label}' has no unitOpId and category "
                        f"'{data.get('category', '')}'. Either match an existing "
                        "unit op or set a specific category (e.g. 'Media Prep')."
                    ),
                    node_id=node_id,
                )
            )

        if node_id not in incoming_targets:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="disconnected_step",
                    message=(
                        f"Step '{label}' has no incoming edge. It is not "
                        "reachable from any Process Start."
                    ),
                    node_id=node_id,
                )
            )

    issues.extend(_branch_role_issues(nodes, edges, graph))
    ok = not any(i.severity == "error" for i in issues)
    return ValidationResult(ok=ok, issues=issues)


def _process_starts_per_component(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    process_starts: list[dict[str, Any]],
) -> list[int]:
    """Count Process Start nodes within each connected component.

    Returns a list of counts (one per component). Components with zero
    Process Starts are excluded — that case is handled by the
    'missing_process_start' rule when the count is zero overall.
    """
    if not nodes:
        return []
    adjacency: dict[str, set[str]] = {n["id"]: set() for n in nodes if "id" in n}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in adjacency and t in adjacency:
            adjacency[s].add(t)
            adjacency[t].add(s)

    process_start_ids = {ps["id"] for ps in process_starts if "id" in ps}
    visited: set[str] = set()
    counts: list[int] = []
    for node_id in adjacency:
        if node_id in visited:
            continue
        stack = [node_id]
        component: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in component:
                continue
            component.add(cur)
            stack.extend(adjacency[cur])
        visited |= component
        ps_in_component = len(component & process_start_ids)
        if ps_in_component:
            counts.append(ps_in_component)
    return counts


def _branch_role_issues(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    graph: dict[str, Any],
) -> list[ValidationIssue]:
    """Fire branch_requires_distinct_roles when a unit op has 2+ outgoing
    branches sharing parentIds (or with null parentId), unless time mode is
    enabled and the immediate target intervals are pairwise disjoint."""
    issues: list[ValidationIssue] = []
    nodes_by_id = {n["id"]: n for n in nodes if "id" in n}
    outgoing: dict[str, list[str]] = {}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s is None or t is None:
            continue
        outgoing.setdefault(s, []).append(t)

    time_enabled = bool(graph.get("timeEnabled"))
    pixels_per_hour = float(graph.get("pixelsPerHour") or 200)
    layout = graph.get("layout") or "horizontal"

    def interval_for(node: dict[str, Any]) -> tuple[float, float]:
        pos = node.get("position") or {}
        axis = float(pos.get("x", 0)) if layout == "horizontal" else float(pos.get("y", 0))
        start = axis / pixels_per_hour * 60.0
        duration = float((node.get("data") or {}).get("duration_min") or 30)
        return (start, start + duration)

    def intervals_pairwise_disjoint(targets: list[dict[str, Any]]) -> bool:
        intervals = [interval_for(t) for t in targets]
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                a, b = intervals[i], intervals[j]
                if not (a[1] <= b[0] or b[1] <= a[0]):
                    return False
        return True

    for source_id, target_ids in outgoing.items():
        src = nodes_by_id.get(source_id)
        if not src or src.get("type") != "unitOp":
            continue
        targets = [
            nodes_by_id[tid]
            for tid in target_ids
            if tid in nodes_by_id and nodes_by_id[tid].get("type") == "unitOp"
        ]
        if len(targets) < 2:
            continue

        parent_ids = [t.get("parentId") for t in targets]
        has_duplicate = len(set(parent_ids)) != len(parent_ids)
        has_null = any(pid is None for pid in parent_ids)
        if not (has_duplicate or has_null):
            continue

        if time_enabled and intervals_pairwise_disjoint(targets):
            continue

        label = (src.get("data") or {}).get("label") or "<unnamed>"
        target_labels = [(t.get("data") or {}).get("label") or "<unnamed>" for t in targets]
        issues.append(
            ValidationIssue(
                severity="error",
                code="branch_requires_distinct_roles",
                node_id=source_id,
                message=(
                    f"Step '{label}' branches to {', '.join(target_labels)} which "
                    "share or lack distinct role assignments. Assign each branch "
                    "target to a different role, or enable time mode and stagger "
                    "the branches at non-overlapping times."
                ),
            )
        )

    return issues


def assert_no_branch_errors(
    graph: dict[str, Any],
    unit_ops: list[UnitOpDefinition],
) -> None:
    """Raise HTTPException(400) if any branch_requires_distinct_roles issue fires.

    Other validation issues (warnings, missing process start, etc.) are not
    enforced here — callers handle them separately if needed.
    """
    from fastapi import HTTPException  # noqa: PLC0415 — keep validation.py import-light

    result = validate_protocol_graph(graph, unit_ops)
    blocking = [i for i in result.issues if i.code == "branch_requires_distinct_roles"]
    if blocking:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "branch_requires_distinct_roles",
                "issues": [i.model_dump() for i in blocking],
            },
        )


__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "validate_protocol_graph",
    "assert_no_branch_errors",
]
