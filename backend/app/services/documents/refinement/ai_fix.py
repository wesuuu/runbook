"""Selection-scoped AI refinement of extracted markdown.

Calls the `document_refinement` capability via `get_model()`. No
business logic beyond prompt assembly + sanitization. Endpoint code
catches exceptions and converts to HTTP errors.
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from pydantic_ai import Agent
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.ai_config import get_model, get_model_display_name

_SYSTEM_PROMPT = (
    "You are correcting OCR / layout-extraction artifacts in scientific "
    "documents. Return only the corrected markdown for the selection — "
    "no preamble, no explanation, no surrounding context."
)


@dataclass
class RefineAiPayload:
    scope: str  # "selection" | "block" | "document"
    selection_markdown: str
    instruction: str
    surrounding_context_markdown: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[list[float]] = None


@dataclass
class RefineAiResult:
    suggested_markdown: str
    model_used: str


def _build_prompt(payload: RefineAiPayload) -> str:
    parts: list[str] = []
    parts.append(f"Instruction: {payload.instruction}")
    if payload.surrounding_context_markdown:
        parts.append(
            "Surrounding context (do not modify, just for grounding):\n"
            f"{payload.surrounding_context_markdown}"
        )
    parts.append("Selection to correct:")
    parts.append(payload.selection_markdown)
    return "\n\n".join(parts)


async def apply_ai_fix(
    db: AsyncSession,
    document_id: UUID,
    org_id: UUID,
    payload: RefineAiPayload,
) -> RefineAiResult:
    model = await get_model("document_refinement", db, org_id=org_id)
    agent = Agent(model, system_prompt=_SYSTEM_PROMPT)
    run = await agent.run(_build_prompt(payload))
    suggested = (run.output or "").strip()
    model_name = await get_model_display_name(
        "document_refinement", db, org_id=org_id
    )
    return RefineAiResult(
        suggested_markdown=suggested, model_used=model_name
    )
