import base64
import json
import logging
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

import httpx
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent
from pydantic_ai.models.openai import OpenAIChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.ai_config import ModelType, get_full_config, get_model

# ── Structured output types ──────────────────────────────────────────


class ExtractedValue(BaseModel):
    field_key: str = Field(description="The parameter key from the schema")
    field_label: str = Field(description="Human-readable label")
    value: float | int | str = Field(description="The extracted value")
    unit: Optional[str] = Field(
        default=None, description="Unit of measurement if applicable"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0")


class ImageAnalysisResult(BaseModel):
    message: str = Field(
        description="Message to display to the user describing what was found"
    )
    extracted_values: list[ExtractedValue] = Field(
        default_factory=list,
        description="Values extracted from the image",
    )
    needs_clarification: bool = Field(
        default=False,
        description="Whether the AI needs more info from the user",
    )


# ── System prompt builder ────────────────────────────────────────────


def build_system_prompt(
    step_name: str,
    param_schema: dict[str, Any],
) -> str:
    """Build a system prompt that gives the AI context about the step."""
    fields_desc = []
    properties = param_schema.get("properties", {})
    for key, prop in properties.items():
        if prop.get("x-ref-type"):
            continue  # Skip reference fields
        label = prop.get("title", key.replace("_", " ").title())
        field_type = prop.get("type", "string")
        unit = prop.get("unit", "")
        unit_str = f" ({unit})" if unit else ""
        fields_desc.append(f"  - {key}: {label}{unit_str} [{field_type}]")

    fields_section = (
        "\n".join(fields_desc) if fields_desc else "  (no specific fields defined)"
    )

    return f"""You are a lab assistant helping a scientist record measurements during a biotech experiment.
You read images of lab instruments and extract values.

CURRENT STEP: {step_name}

EXPECTED MEASUREMENTS:
{fields_section}

INSTRUCTIONS:
1. Identify any visible measurement values in the image.
2. Map each value to a field from the expected measurements list using the exact field_key.
3. Set confidence: 0.8-1.0 for clearly readable values, 0.3-0.7 for unclear ones.
4. In your message, be brief and conversational:
   - State what values you found (e.g. "I can see the temperature reads 34.6°C.")
   - Ask the user to confirm: "Does that look right?" or "Should I record this?"
   - If something is unclear, ask a specific question (e.g. "Is that reading 34.6 or 34.8?")
5. If you cannot determine which field a value belongs to, set needs_clarification to true.
6. Keep your message to 1-3 sentences. Do NOT write long descriptions of the equipment."""


_JSON_FORMAT_INSTRUCTIONS = """

You MUST respond with valid JSON matching this schema:
{{
  "message": "Brief conversational message (1-3 sentences). State values found and ask user to confirm.",
  "extracted_values": [
    {{
      "field_key": "the_key_from_expected_measurements",
      "field_label": "Human Readable Label",
      "value": 123.45,
      "unit": "unit_string_or_null",
      "confidence": 0.95
    }}
  ],
  "needs_clarification": false
}}

IMPORTANT: The "message" field must be a short, friendly sentence — NOT a description of the equipment.
Example message: "I read 34.6°C from the display. Should I record this as the water bath temperature?"

Return ONLY the JSON object, no other text."""


def build_conversation_prompt(
    step_name: str,
    param_schema: dict[str, Any],
) -> str:
    """Build a system prompt for follow-up conversation turns."""
    properties = param_schema.get("properties", {})
    fields_desc = []
    for key, prop in properties.items():
        if prop.get("x-ref-type"):
            continue
        label = prop.get("title", key.replace("_", " ").title())
        unit = prop.get("unit", "")
        unit_str = f" ({unit})" if unit else ""
        fields_desc.append(f"  - {key}: {label}{unit_str}")

    fields_section = (
        "\n".join(fields_desc) if fields_desc else "  (no specific fields defined)"
    )

    return f"""You are a lab assistant in a follow-up conversation about a measurement image.

CURRENT STEP: {step_name}

EXPECTED MEASUREMENTS:
{fields_section}

Based on the user's feedback:
1. Update extracted values if they provided corrections.
2. If they confirmed values, keep them with high confidence (1.0).
3. If they clarified which field a value belongs to, update the mapping.
4. Set needs_clarification to false if no further questions remain.
5. Keep your message brief (1-2 sentences). Acknowledge their input and confirm what you'll record."""


# ── Agent creation ────────────────────────────────────────────────────


def create_vision_agent(
    system_prompt: str,
    model: "ModelType | str" = "test",
) -> Agent[None, ImageAnalysisResult]:
    """Create a pydantic-ai agent for image analysis."""
    return Agent(
        model,
        output_type=ImageAnalysisResult,
        instructions=system_prompt,
    )


# ── Ollama native API ────────────────────────────────────────────────


def _is_ollama_model(model: "ModelType | str") -> bool:
    """Check if the model is an Ollama model."""
    if isinstance(model, OpenAIChatModel):
        from pydantic_ai.providers.ollama import OllamaProvider

        return isinstance(model._provider, OllamaProvider)
    if isinstance(model, str) and model.startswith("ollama:"):
        return True
    return False


def _get_ollama_model_name(model: "ModelType | str") -> str:
    """Extract the model name from an Ollama model."""
    if isinstance(model, OpenAIChatModel):
        return model.model_name
    if isinstance(model, str) and model.startswith("ollama:"):
        return model.split(":", 1)[1]
    return str(model)


async def _ollama_chat(
    base_url: str,
    model_name: str,
    system_prompt: str,
    user_text: str,
    image_bytes: bytes | None = None,
) -> ImageAnalysisResult:
    """Call Ollama's native /api/chat endpoint with vision support."""
    messages = [
        {"role": "system", "content": system_prompt + _JSON_FORMAT_INSTRUCTIONS},
    ]

    user_msg: dict[str, Any] = {"role": "user", "content": user_text}
    if image_bytes:
        user_msg["images"] = [base64.b64encode(image_bytes).decode("utf-8")]
    messages.append(user_msg)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model_name,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {"num_predict": 512},
            },
        )
        resp.raise_for_status()

    data = resp.json()
    content = data.get("message", {}).get("content", "")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return ImageAnalysisResult(
            message=content[:500] if content else "Failed to parse AI response.",
            extracted_values=[],
            needs_clarification=True,
        )

    # Try full validation first
    try:
        return ImageAnalysisResult.model_validate(parsed)
    except Exception as e:
        logger.warning(
            "Full ImageAnalysisResult validation failed, extracting best-effort: %s", e
        )
        # Validation failed — extract what we can from the parsed JSON
        message = parsed.get("message", "")
        if not isinstance(message, str):
            message = str(message)

        # Best-effort extraction of values
        raw_values = parsed.get("extracted_values", [])
        extracted = []
        if isinstance(raw_values, list):
            for rv in raw_values:
                if not isinstance(rv, dict):
                    continue
                try:
                    extracted.append(ExtractedValue.model_validate(rv))
                except Exception:
                    logger.debug("Skipping invalid extracted value: %s", rv)

        return ImageAnalysisResult(
            message=message
            or "I analyzed the image but had trouble formatting the results.",
            extracted_values=extracted,
            needs_clarification=parsed.get("needs_clarification", True),
        )


# ── Service functions ─────────────────────────────────────────────────


async def analyze_image(
    image_path: str,
    step_name: str,
    param_schema: dict[str, Any],
    db: AsyncSession,
    model_override: "ModelType | str | None" = None,
    org_id: "UUID | None" = None,
) -> ImageAnalysisResult:
    """Analyze a lab instrument image and extract measurement values."""
    model = model_override or await get_model("vision", db, org_id=org_id)
    system_prompt = build_system_prompt(step_name, param_schema)

    image_bytes = Path(image_path).read_bytes()

    # Use Ollama native API for Ollama models (no tool-use requirement)
    if _is_ollama_model(model):
        config = await get_full_config("vision", db, org_id=org_id)
        creds = config.get("credentials") or {}
        base_url = creds.get("base_url") or "http://localhost:11434"
        model_name = _get_ollama_model_name(model)
        return await _ollama_chat(
            base_url=base_url,
            model_name=model_name,
            system_prompt=system_prompt,
            user_text="Please analyze this image and extract any visible measurement values.",
            image_bytes=image_bytes,
        )

    # For cloud providers, use pydantic-ai with structured output (tool calling)
    agent = create_vision_agent(system_prompt, model=model)
    mime_type = _guess_mime(image_path)
    user_content = [
        BinaryContent(data=image_bytes, media_type=mime_type),
        "Please analyze this image and extract any visible measurement values.",
    ]
    result = await agent.run(user_content)
    return result.output


async def continue_conversation(
    image_path: str,
    step_name: str,
    param_schema: dict[str, Any],
    messages: list[dict[str, Any]],
    user_reply: str,
    db: AsyncSession,
    model_override: "ModelType | str | None" = None,
    org_id: "UUID | None" = None,
) -> ImageAnalysisResult:
    """Continue a multi-turn conversation about an image."""
    model = model_override or await get_model("vision", db, org_id=org_id)
    system_prompt = build_conversation_prompt(step_name, param_schema)

    image_bytes = Path(image_path).read_bytes()
    history_text = _format_history(messages)

    # Use Ollama native API for Ollama models
    if _is_ollama_model(model):
        config = await get_full_config("vision", db, org_id=org_id)
        creds = config.get("credentials") or {}
        base_url = creds.get("base_url") or "http://localhost:11434"
        model_name = _get_ollama_model_name(model)
        return await _ollama_chat(
            base_url=base_url,
            model_name=model_name,
            system_prompt=system_prompt,
            user_text=f"{history_text}\n\nUser's latest reply: {user_reply}",
            image_bytes=image_bytes,
        )

    # For cloud providers, use pydantic-ai with structured output
    agent = create_vision_agent(system_prompt, model=model)
    mime_type = _guess_mime(image_path)
    user_content = [
        BinaryContent(data=image_bytes, media_type=mime_type),
        f"{history_text}\n\nUser's latest reply: {user_reply}",
    ]
    result = await agent.run(user_content)
    return result.output


def _guess_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    return mime_map.get(ext, "image/jpeg")


def _format_history(messages: list[dict[str, Any]]) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        lines.append(f"{role.upper()}: {content}")
    return "\n".join(lines)


# ── Document text extraction (OCR) ──────────────────────────────────


_DOC_OCR_PROMPT = """You are a document OCR assistant. Extract ALL text from this image of a document or protocol.

RULES:
1. Preserve the document structure: headings, numbered steps, bullet points, tables.
2. Return the extracted text as plain text, maintaining the original formatting.
3. If text is unclear or partially obscured, include your best reading with [?] markers.
4. Do NOT summarize or interpret — extract the raw text faithfully."""


async def extract_document_text(
    image_path: str,
    db: AsyncSession,
    org_id: "UUID | None" = None,
) -> str:
    """Extract text from a document/protocol image using vision AI.

    Used for photo-based protocol import (camera capture or scanned images).
    Returns the extracted text as a plain string.
    """
    model = await get_model("vision", db, org_id=org_id)
    image_bytes = Path(image_path).read_bytes()

    if _is_ollama_model(model):
        config = await get_full_config("vision", db, org_id=org_id)
        creds = config.get("credentials") or {}
        base_url = creds.get("base_url") or "http://localhost:11434"
        model_name = _get_ollama_model_name(model)

        # Use Ollama native API without JSON format (we want plain text)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/api/chat",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": _DOC_OCR_PROMPT},
                        {
                            "role": "user",
                            "content": "Extract all text from this document image.",
                            "images": [base64.b64encode(image_bytes).decode("utf-8")],
                        },
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()

        data = resp.json()
        return data.get("message", {}).get("content", "")

    # Cloud providers: use pydantic-ai with plain string output
    agent = Agent(model, system_prompt=_DOC_OCR_PROMPT, output_type=str)
    mime_type = _guess_mime(image_path)
    user_content = [
        BinaryContent(data=image_bytes, media_type=mime_type),
        "Extract all text from this document image.",
    ]
    result = await agent.run(user_content)
    return result.output
