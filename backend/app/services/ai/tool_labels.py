"""Central resolver for chat-agent tool display labels (F-0083).

Each subagent's tools.py exposes its own TOOL_LABELS dict next to the tool
functions. This module aggregates them and exposes a single lookup, with a
hardcoded entry for the auto-injected subagent-dispatch toolset (task,
check_task, answer_subagent) from subagents-pydantic-ai.
"""

from app.services.ai.subagents.research_library.tools import \
    TOOL_LABELS as _RESEARCH_LIBRARY_LABELS
from app.services.ai.subagents.shared.protocols.tools import \
    TOOL_LABELS as _PROTOCOL_LABELS

FALLBACK_LABEL = "Working…"

# Auto-injected by subagents-pydantic-ai capability — fired on the PARENT
# agent when it dispatches to a subagent or receives a subagent answer.
_DISPATCH_LABELS: dict[str, str] = {
    "task": "Thinking…",
    "check_task": "Checking progress…",
    "answer_subagent": "Wrapping up…",
}

_ALL_LABELS: dict[str, str] = {
    **_RESEARCH_LIBRARY_LABELS,
    **_PROTOCOL_LABELS,
    **_DISPATCH_LABELS,
}


def resolve_tool_label(tool_name: str) -> str:
    """Return the human-readable label for a tool name.

    Falls back to FALLBACK_LABEL for unknown tools so the indicator still
    updates; the coverage test in tests/unit/test_tool_labels.py prevents
    real tools from hitting this path.
    """
    return _ALL_LABELS.get(tool_name, FALLBACK_LABEL)
