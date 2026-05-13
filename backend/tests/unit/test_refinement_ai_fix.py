from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.documents.refinement.ai_fix import (RefineAiPayload,
                                                      apply_ai_fix)


@pytest.mark.asyncio
async def test_apply_ai_fix_returns_suggested_markdown():
    payload = RefineAiPayload(
        scope="selection",
        selection_markdown="NaHzPO4119.98",
        instruction="Fix OCR artifact",
    )
    fake_agent = MagicMock()
    fake_run = MagicMock()
    fake_run.output = "NaH2PO4 119.98"
    fake_agent.run = AsyncMock(return_value=fake_run)

    with patch(
        "app.services.documents.refinement.ai_fix.get_model",
        AsyncMock(return_value="anthropic:claude-sonnet-4-5-20250929"),
    ), patch(
        "app.services.documents.refinement.ai_fix.Agent",
        return_value=fake_agent,
    ), patch(
        "app.services.documents.refinement.ai_fix.get_model_display_name",
        AsyncMock(return_value="claude-sonnet-4-5-20250929"),
    ):
        result = await apply_ai_fix(
            db=MagicMock(),
            document_id=uuid4(),
            org_id=uuid4(),
            payload=payload,
        )

    assert result.suggested_markdown == "NaH2PO4 119.98"
    assert "claude" in result.model_used


@pytest.mark.asyncio
async def test_apply_ai_fix_includes_surrounding_context_in_prompt():
    payload = RefineAiPayload(
        scope="block",
        selection_markdown="cell text",
        instruction="fix the cell",
        surrounding_context_markdown="...before... |cell text| ...after...",
    )
    captured: dict = {}
    fake_agent = MagicMock()

    async def _run(prompt):
        captured["prompt"] = prompt
        r = MagicMock()
        r.output = "fixed cell"
        return r

    fake_agent.run = _run

    with patch(
        "app.services.documents.refinement.ai_fix.get_model",
        AsyncMock(return_value="x"),
    ), patch(
        "app.services.documents.refinement.ai_fix.Agent",
        return_value=fake_agent,
    ), patch(
        "app.services.documents.refinement.ai_fix.get_model_display_name",
        AsyncMock(return_value="x"),
    ):
        await apply_ai_fix(
            db=MagicMock(),
            document_id=uuid4(),
            org_id=uuid4(),
            payload=payload,
        )

    assert "...before..." in captured["prompt"]
    assert "cell text" in captured["prompt"]
    assert "fix the cell" in captured["prompt"]
