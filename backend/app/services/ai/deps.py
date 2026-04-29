"""Per-request dependencies injected into pydantic-ai tools and subagents.

ChatDeps satisfies SubAgentDepsProtocol from subagents-pydantic-ai (structural
typing — no inheritance).
"""
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class RetrievedChunk:
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    page_number: int | None
    content: str
    score: float


@dataclass
class ChatDeps:
    """Dependencies injected into pydantic-ai tools via RunContext."""

    db: AsyncSession
    org_id: UUID
    user_id: UUID
    is_org_admin: bool
    sources: list[RetrievedChunk] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    subagents: dict[str, Any] = field(default_factory=dict)

    def clone_for_subagent(self, max_depth: int = 0) -> "ChatDeps":
        """Create deps for a subagent run.

        - db / org_id / user_id / is_org_admin: shared (request scope)
        - sources / tool_calls: shared so subagent citations and tool-call
          audit rows bubble up to the parent (mutated in place)
        - subagents: preserved when max_depth > 0 (nested dispatch allowed),
          wiped at max_depth == 0 (leaf subagent)
        """
        return ChatDeps(
            db=self.db,
            org_id=self.org_id,
            user_id=self.user_id,
            is_org_admin=self.is_org_admin,
            sources=self.sources,
            tool_calls=self.tool_calls,
            subagents={} if max_depth <= 0 else self.subagents,
        )
