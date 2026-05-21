"""Tests for ChatDeps shape and clone_for_subagent semantics."""

import uuid
from unittest.mock import MagicMock

from subagents_pydantic_ai import SubAgentDepsProtocol

from app.services.ai.deps import ChatDeps, RetrievedChunk


def make_deps(**overrides) -> ChatDeps:
    base = dict(
        db=MagicMock(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        is_org_admin=False,
    )
    base.update(overrides)
    return ChatDeps(**base)


def test_chat_deps_satisfies_subagent_protocol():
    deps = make_deps()
    assert isinstance(deps, SubAgentDepsProtocol)


def test_clone_at_max_depth_zero_wipes_subagents():
    deps = make_deps()
    deps.subagents = {"foo": "bar"}
    cloned = deps.clone_for_subagent(max_depth=0)
    assert cloned.subagents == {}


def test_clone_at_max_depth_one_preserves_subagents():
    deps = make_deps()
    deps.subagents = {"foo": "bar"}
    cloned = deps.clone_for_subagent(max_depth=1)
    assert cloned.subagents == {"foo": "bar"}


def test_clone_shares_sources_list_for_aggregation():
    deps = make_deps()
    cloned = deps.clone_for_subagent(max_depth=0)
    cloned.sources.append(
        RetrievedChunk(
            document_id=uuid.uuid4(),
            document_slug="t",
            document_title="t",
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            page_number=None,
            content="c",
            score=1.0,
        )
    )
    # Mutation in the clone shows up in the parent — that's the design
    assert len(deps.sources) == 1


def test_clone_shares_tool_calls_list():
    deps = make_deps()
    cloned = deps.clone_for_subagent(max_depth=0)
    cloned.tool_calls.append({"tool": "search_documents"})
    assert len(deps.tool_calls) == 1


def test_clone_preserves_db_and_identity_fields():
    deps = make_deps()
    cloned = deps.clone_for_subagent()
    assert cloned.db is deps.db
    assert cloned.org_id == deps.org_id
    assert cloned.user_id == deps.user_id
    assert cloned.is_org_admin == deps.is_org_admin
