"""Chat agent subagent registry.

protocol_builder is legacy — unregistered in chat_agent.py but kept on
disk this cycle.
"""

from . import (
    protocol_builder,
    protocol_creator,
    protocol_editor,
    protocol_knowledgebase,
    research_library,
    run_planner,
)

__all__ = [
    "protocol_builder",
    "protocol_creator",
    "protocol_editor",
    "protocol_knowledgebase",
    "research_library",
    "run_planner",
]
