"""Invariants for the chat tool-label registry (F-0083).

Ensures every tool name audited via ctx.deps.tool_calls.append({"tool": ...})
under app/services/ai/subagents/ (excluding the legacy, unwired
protocol_builder package) has a corresponding TOOL_LABELS entry and resolves
to a non-fallback human label.
"""
import re
from pathlib import Path

import pytest

from app.services.ai.tool_labels import FALLBACK_LABEL, resolve_tool_label

SUBAGENTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "app" / "services" / "ai" / "subagents"
)
_TOOL_AUDIT_RE = re.compile(r'"tool"\s*:\s*"([a-z_][a-z0-9_]*)"')

# protocol_builder is on-disk legacy — unregistered in chat_agent.py since the
# TD-0086 split into protocol_creator + protocol_editor. Skip its audits.
_LEGACY_DIRS = {"protocol_builder"}


def _audited_tool_names() -> set[str]:
    names: set[str] = set()
    for tools_py in SUBAGENTS_DIR.rglob("tools.py"):
        # Exclude the legacy package and anything else marked legacy.
        if any(part in _LEGACY_DIRS for part in tools_py.parts):
            continue
        names.update(_TOOL_AUDIT_RE.findall(tools_py.read_text()))
    return names


def test_audited_tools_discovered():
    """Sanity: the scan finds the known tools from the active subagents."""
    names = _audited_tool_names()
    assert "search_documents" in names           # research_library
    assert "create_protocol" in names            # shared/protocols
    assert "set_node_position" in names          # shared/protocols (post-TD-0086)
    # research_library (3) + shared/protocols (21) = 24+
    assert len(names) >= 24


@pytest.mark.parametrize("tool_name", sorted(_audited_tool_names()))
def test_every_audited_tool_has_a_label(tool_name: str):
    """Each audited tool must resolve to a non-fallback label."""
    label = resolve_tool_label(tool_name)
    assert label != FALLBACK_LABEL, (
        f"Tool {tool_name!r} has no TOOL_LABELS entry. Add it to the "
        f"subagent's tools.py TOOL_LABELS dict."
    )
    assert label.endswith("…"), f"Label for {tool_name!r} should end with an ellipsis"


def test_subagent_dispatch_tools_have_labels():
    """Auto-injected subagent toolset (task/check_task/answer_subagent) is labeled."""
    assert resolve_tool_label("task") != FALLBACK_LABEL
    assert resolve_tool_label("check_task") != FALLBACK_LABEL
    assert resolve_tool_label("answer_subagent") != FALLBACK_LABEL


def test_unknown_tool_falls_back():
    assert resolve_tool_label("nonexistent_tool_xyz") == FALLBACK_LABEL


def test_resolves_protocol_knowledgebase_labels():
    assert resolve_tool_label("search_openwetware") == "Searching OpenWetWare…"
    assert (
        resolve_tool_label("fetch_openwetware_protocol")
        == "Reading external protocol…"
    )
