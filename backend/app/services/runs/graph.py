"""Pure graph-navigation + audit-label helpers for runs.

Used by both `app.services.runs.overrides` and by the existing audit /
validation code in `app.api.endpoints.runs`. Single source of truth for:
  - filtering a graph's nodes to just unit-op nodes
  - deriving a human-readable field label from a paramSchema property
"""
from typing import Iterator, Optional


def iter_unit_op_nodes(graph: Optional[dict]) -> Iterator[dict]:
    """Yield every node in `graph["nodes"]` whose `type == "unitOp"`.

    Tolerant of `graph` being None, missing the `nodes` key, or having
    `nodes` set to None — returns an empty iterator in all those cases.
    """
    if not graph:
        return
    nodes = graph.get("nodes") or []
    for node in nodes:
        if isinstance(node, dict) and node.get("type") == "unitOp":
            yield node


def derive_field_label(schema_props: Optional[dict], key: str) -> str:
    """Return a human-readable label for a paramSchema property key.

    Prefers the `title` from the schema; falls back to a humanized version
    of the key (snake_case → Title Case). Tolerant of `schema_props` being
    None or the key being absent.
    """
    if isinstance(schema_props, dict):
        prop = schema_props.get(key, {}) or {}
        title = prop.get("title") if isinstance(prop, dict) else None
        if title:
            return title
    return key.replace("_", " ").title()
