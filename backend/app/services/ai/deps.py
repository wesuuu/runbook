"""Per-request dependencies injected into pydantic-ai tools and subagents.

ChatDeps satisfies SubAgentDepsProtocol from subagents-pydantic-ai (structural
typing — no inheritance).
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
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
    # Cache of external protocol payloads keyed by source URL — the LLM
    # would otherwise round-trip multi-KB JSON and sometimes truncates it,
    # dropping steps.
    external_protocol_cache: dict[str, str] = field(default_factory=dict)
    # Human-readable deviation strings from the user's inline edits on the
    # approval card. Stashed by the resume path so the approval tool body
    # can fold them into the sentinel + audit row.
    user_deviations: list[str] = field(default_factory=list)
    # Setting event_stream_handler on a subagent forces streaming mode, which
    # some models (Ollama gpt-oss) reject — hence the deps-callback route.
    tool_event_callback: Callable[[str, str], Awaitable[None]] | None = None
    # Serializes DB-mutating tool calls so that parallel tool dispatch from the
    # LLM doesn't trigger concurrent flushes on the shared AsyncSession
    # ("Session is already flushing"). Tools that write to the DB must
    # acquire this lock for the duration of their service call. Sharing the
    # same lock across the parent and any cloned subagent deps ensures cross-
    # agent serialization too.
    db_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def clone_for_subagent(self, max_depth: int = 0) -> "ChatDeps":
        """Create deps for a subagent run.

        - db / org_id / user_id / is_org_admin: shared (request scope)
        - sources / tool_calls: shared so subagent citations and tool-call
          audit rows bubble up to the parent (mutated in place)
        - subagents: preserved when max_depth > 0 (nested dispatch allowed),
          wiped at max_depth == 0 (leaf subagent)
        - tool_event_callback: propagated so subagent tool wrappers can emit
          live tool-call events to the parent's SSE stream
        """
        return ChatDeps(
            db=self.db,
            org_id=self.org_id,
            user_id=self.user_id,
            is_org_admin=self.is_org_admin,
            sources=self.sources,
            tool_calls=self.tool_calls,
            subagents={} if max_depth <= 0 else self.subagents,
            external_protocol_cache=self.external_protocol_cache,
            user_deviations=self.user_deviations,
            tool_event_callback=self.tool_event_callback,
            db_lock=self.db_lock,
        )
