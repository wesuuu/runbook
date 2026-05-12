"""Sanity test for pydantic-ai's requires_approval / DeferredToolRequests flow.

Locks down the contract we depend on in send_message_streaming and the
approve endpoint (F-0084).
"""

from __future__ import annotations

import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults


@pytest.mark.asyncio
async def test_requires_approval_returns_deferred_requests():
    calls: list[str] = []

    async def _danger(_ctx, payload: str) -> str:
        calls.append(payload)
        return f"executed:{payload}"

    agent: Agent = Agent(
        "test",
        instructions="Always call the `danger` tool with payload='hello'.",
        tools=[Tool(_danger, requires_approval=True)],
        output_type=[str, DeferredToolRequests],
    )

    result = await agent.run("please call danger")
    assert isinstance(result.output, DeferredToolRequests)
    assert len(result.output.approvals) == 1
    assert calls == []

    call_id = result.output.approvals[0].tool_call_id
    resumed = await agent.run(
        deferred_tool_results=DeferredToolResults(approvals={call_id: True}),
        message_history=result.all_messages(),
    )
    # Contract: after approval the tool body executes exactly once.
    # (The pydantic-ai `test` model fills string args deterministically,
    # not from the instructions, so we don't pin the payload value.)
    assert len(calls) == 1
    assert resumed.output


@pytest.mark.asyncio
async def test_rejection_does_not_execute_tool():
    calls: list[str] = []

    async def _danger(_ctx, payload: str) -> str:
        calls.append(payload)
        return "executed"

    agent: Agent = Agent(
        "test",
        instructions="Call `danger` with payload='hi'.",
        tools=[Tool(_danger, requires_approval=True)],
        output_type=[str, DeferredToolRequests],
    )
    result = await agent.run("call it")
    assert isinstance(result.output, DeferredToolRequests)
    call_id = result.output.approvals[0].tool_call_id
    await agent.run(
        deferred_tool_results=DeferredToolResults(approvals={call_id: False}),
        message_history=result.all_messages(),
    )
    assert calls == []
