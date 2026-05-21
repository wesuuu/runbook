"""Single-pass run-graph walker for the dashboard (F-0092).

The dashboard needs three independent facts out of every run's graph JSONB.
Walking each graph exactly once here keeps every consuming service from
re-parsing the same JSONB — the CPU half of "no N+1 regressions".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID


@dataclass
class RunGraphFacts:
    """Everything the dashboard pulls from a single run graph."""

    swimlane_node_ids: list[str] = field(default_factory=list)
    equipment_ids: list[UUID] = field(default_factory=list)
    unit_op_node_ids: list[str] = field(default_factory=list)


def extract_graph_facts(graph: Optional[dict]) -> RunGraphFacts:
    """Walk a run graph once; collect everything the dashboard needs from it.

    Tolerant of a None/empty graph, a missing ``nodes`` key, ``nodes`` set
    to None, or non-dict entries inside ``nodes``.
    """
    facts = RunGraphFacts()
    nodes = (graph or {}).get("nodes") or []
    seen_equipment: set[UUID] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        node_id = node.get("id")
        if node_type == "swimLane" and node_id:
            facts.swimlane_node_ids.append(node_id)
        elif node_type == "unitOp" and node_id:
            facts.unit_op_node_ids.append(node_id)
            # Equipment only lives on unitOp nodes — consistent with
            # template_engine.py.
            data = node.get("data") or {}
            for eq in data.get("equipment") or []:
                if not isinstance(eq, dict):
                    continue
                raw = eq.get("equipment_id")
                if not raw:
                    continue
                try:
                    eq_id = UUID(str(raw))
                except (ValueError, AttributeError, TypeError):
                    continue
                if eq_id not in seen_equipment:
                    seen_equipment.add(eq_id)
                    facts.equipment_ids.append(eq_id)
    return facts
