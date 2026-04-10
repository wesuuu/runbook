"""Batch record extraction service.

Extracts structured data (steps, parameter values, timestamps, signatures,
deviations) from uploaded paper batch records using AI vision/text models,
then maps the extraction to a user-selected protocol's graph structure.
"""

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.batch_record_import import (
    BatchRecordImport,
    BatchRecordImportStatus,
)
from app.models.jobs import BackgroundJob
from app.models.science import Protocol
from app.services.ai_config import get_model, get_full_config
from app.services.background_jobs import BackgroundJobService
from app.services.graph_processing import _parse_graph_roles_and_steps

logger = logging.getLogger(__name__)


# ── Pydantic models for LLM structured output ───────────────────────


class ExtractedParameterValue(BaseModel):
    """A single parameter reading from a batch record."""

    field_label: str = Field(description="Human label from the form")
    value: float | int | str = Field(description="The recorded value")
    unit: Optional[str] = Field(
        default=None, description="Unit of measurement"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence: 0.9+ typed, 0.5-0.8 handwritten, <0.5 illegible",
    )
    source_page: Optional[int] = Field(
        default=None, description="Page number where this was found"
    )


class ExtractedTimestamp(BaseModel):
    """A timestamp extracted from a batch record."""

    value: str = Field(description="ISO 8601 or raw text")
    label: str = Field(description="e.g. Step start, Step complete")
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedSignature(BaseModel):
    """An operator signature/initials from a batch record."""

    initials_or_name: str
    role: Optional[str] = Field(
        default=None, description="e.g. Operator, QC"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedDeviation(BaseModel):
    """A deviation or note from a batch record."""

    description: str
    severity: Optional[str] = Field(
        default=None, description="e.g. minor, major"
    )
    step_reference: Optional[str] = Field(
        default=None, description="Which step this deviation relates to"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedStep(BaseModel):
    """A single step extracted from a batch record."""

    step_name: str
    step_number: Optional[int] = None
    description: str = ""
    parameters: list[ExtractedParameterValue] = []
    timestamps: list[ExtractedTimestamp] = []
    signatures: list[ExtractedSignature] = []
    deviations: list[ExtractedDeviation] = []
    notes: str = ""
    confidence: float = Field(
        ge=0.0, le=1.0, description="Overall step confidence"
    )
    source_page: Optional[int] = None


class BatchRecordExtraction(BaseModel):
    """Complete extraction from a batch record document."""

    document_title: str = ""
    batch_id: Optional[str] = Field(
        default=None, description="Batch/lot number if found"
    )
    product_name: Optional[str] = None
    date: Optional[str] = Field(
        default=None, description="Execution date"
    )
    steps: list[ExtractedStep] = []
    general_notes: list[str] = []
    overall_confidence: float = Field(ge=0.0, le=1.0)


class StepMapping(BaseModel):
    """Mapping of an extracted step to a protocol graph step."""

    extracted_step_index: int
    extracted_step_name: str
    protocol_step_id: str
    protocol_step_name: str
    score: float = Field(ge=0.0, le=1.0)
    param_mappings: list["ParamMapping"] = []


class ParamMapping(BaseModel):
    """Mapping of an extracted parameter to a protocol param schema field."""

    extracted_param_index: int
    extracted_label: str
    extracted_value: Any = None
    extracted_unit: Optional[str] = None
    schema_field_key: str
    schema_field_label: str
    confidence: float = Field(ge=0.0, le=1.0)


class StepMappingResult(BaseModel):
    """LLM output: mapping of extracted steps to protocol steps."""

    mappings: list[StepMapping] = []


# ── LLM prompts ──────────────────────────────────────────────────────


BATCH_RECORD_SYSTEM_PROMPT = """You are analyzing a FILLED-IN paper batch record from a biotech laboratory.
This is NOT an empty template — it contains actual recorded values from a completed process.

Extract ALL of the following from the document:
1. Step names and their order (step_number if visible)
2. Parameter values WITH units (pH, temperature, volume, mass, concentration, etc.)
3. Timestamps (start times, end times, durations)
4. Operator signatures or initials
5. Any deviations, notes, or observations recorded
6. Batch/lot number, product name, execution date if present

Confidence scoring:
- 0.9-1.0: Clearly typed or printed text
- 0.7-0.89: Legible handwriting
- 0.5-0.69: Partially legible, some uncertainty
- Below 0.5: Largely illegible, best guess

Always report the source page number for each extraction.
Return the complete structured extraction as JSON."""


def _build_mapping_prompt(
    extraction: BatchRecordExtraction,
    flat_steps: list[dict],
) -> str:
    """Build the prompt for LLM-based step and parameter mapping."""
    extracted_lines = []
    for i, step in enumerate(extraction.steps):
        params = ", ".join(
            f"{p.field_label}={p.value}{(' ' + p.unit) if p.unit else ''}"
            for p in step.parameters
        )
        extracted_lines.append(
            f"  [{i}] \"{step.step_name}\": {params or '(no params)'}"
        )

    protocol_lines = []
    for step in flat_steps:
        schema = step.get("param_schema") or {}
        props = schema.get("properties", {})
        fields = ", ".join(
            f"{k} ({v.get('title', k)})"
            for k, v in props.items()
        )
        protocol_lines.append(
            f"  \"{step['id']}\" \"{step['name']}\": {fields or '(no params)'}"
        )

    return f"""Map extracted batch record steps to protocol steps.

EXTRACTED STEPS (from paper batch record):
{chr(10).join(extracted_lines)}

PROTOCOL STEPS (digital protocol):
{chr(10).join(protocol_lines)}

For each extracted step, find the best matching protocol step.
For each extracted parameter within a matched step, find the best matching
param_schema field key.

Return a JSON object with a "mappings" array. Each mapping has:
- extracted_step_index: int (index in extracted list)
- extracted_step_name: str
- protocol_step_id: str (the ID from the protocol)
- protocol_step_name: str
- score: float (0.0-1.0 confidence in the match)
- param_mappings: array of objects with:
  - extracted_param_index: int (index in that step's parameters)
  - extracted_label: str
  - extracted_value: the value
  - extracted_unit: str or null
  - schema_field_key: str (the property key from param_schema)
  - schema_field_label: str
  - confidence: float

Only include mappings where you are at least somewhat confident (score > 0.3).
Leave out steps/params you cannot match."""


# ── Extraction functions ─────────────────────────────────────────────


_CHUNK_SIZE = 5  # pages per chunk for fallback extraction


async def extract_batch_record_pages(
    file_path: Path,
    mime_type: str,
    db: AsyncSession,
    org_id: UUID | None = None,
) -> tuple[str, list[tuple[int, bytes]]]:
    """Extract text and page images from a batch record document.

    Returns:
        (full_text, page_images) where page_images is a list of
        (page_number, png_bytes) for vision analysis.
    """
    if mime_type == "application/pdf":
        from app.services.document_processor import extract_pdf_pages

        pages = await asyncio.to_thread(extract_pdf_pages, file_path, True)
        text = "\n\n".join(p.text for p in pages if p.text)
        images = [
            (p.page_number, p.image_bytes)
            for p in pages
            if p.image_bytes
        ]
        return text, images

    if mime_type.startswith("image/"):
        from app.services.ai_vision import extract_document_text

        text = await extract_document_text(str(file_path), db, org_id)
        image_bytes = await asyncio.to_thread(file_path.read_bytes)
        return text, [(1, image_bytes)]

    # Fallback: text-only extraction (DOCX, etc.)
    from app.services.protocol_importer import extract_text

    text = await extract_text(file_path, mime_type, db, org_id)
    return text, []


async def extract_batch_record_data(
    text: str,
    page_images: list[tuple[int, bytes]] | None,
    db: AsyncSession,
    org_id: UUID | None = None,
) -> BatchRecordExtraction:
    """Extract structured data from batch record using LLM.

    Tries a single call with all pages first. On context overflow,
    falls back to chunked extraction.
    """
    try:
        return await _extract_single_call(text, page_images, db, org_id)
    except Exception as exc:
        error_msg = str(exc).lower()
        context_errors = (
            "context length", "too many tokens", "token limit",
            "max_tokens", "context_window", "context window",
            "maximum context", "content too large",
        )
        if any(err in error_msg for err in context_errors):
            logger.info(
                "Single-call extraction hit context limit, "
                "falling back to chunked extraction"
            )
            return await _extract_chunked(text, page_images, db, org_id)
        raise


async def _extract_single_call(
    text: str,
    page_images: list[tuple[int, bytes]] | None,
    db: AsyncSession,
    org_id: UUID | None = None,
) -> BatchRecordExtraction:
    """Extract from all pages in a single LLM call."""
    from app.services.ai_vision import (
        _is_ollama_model,
        _get_ollama_model_name,
    )

    if page_images:
        model = await get_model("vision", db, org_id=org_id)
    else:
        model = await get_model("text", db, org_id=org_id)

    # Ollama models don't support tool-calling — use native API
    if _is_ollama_model(model):
        return await _ollama_extract(
            text, page_images, model, db, org_id,
        )

    # Cloud providers: use pydantic-ai with structured output
    agent = Agent(
        model,
        output_type=BatchRecordExtraction,
        instructions=BATCH_RECORD_SYSTEM_PROMPT,
    )

    user_parts: list[Any] = []
    if text:
        user_parts.append(f"Document text:\n\n{text}")
    if page_images:
        for page_num, img_bytes in page_images:
            user_parts.append(f"--- Page {page_num} ---")
            user_parts.append(
                BinaryContent(data=img_bytes, media_type="image/png")
            )

    if not user_parts:
        return BatchRecordExtraction(overall_confidence=0.0)

    result = await agent.run(user_parts)
    return result.output


async def _ollama_extract(
    text: str,
    page_images: list[tuple[int, bytes]] | None,
    model: Any,
    db: AsyncSession,
    org_id: UUID | None = None,
) -> BatchRecordExtraction:
    """Extract batch record data using Ollama's native /api/chat API."""
    from app.services.ai_vision import _get_ollama_model_name

    config = await get_full_config("vision", db, org_id=org_id)
    creds = config.get("credentials") or {}
    base_url = creds.get("base_url") or "http://localhost:11434"
    model_name = _get_ollama_model_name(model)

    schema_hint = (
        '\n\nReturn your response as JSON matching this structure:\n'
        '{"document_title": "", "batch_id": null, "product_name": null, '
        '"date": null, "steps": [{"step_name": "", "step_number": null, '
        '"parameters": [{"field_label": "", "value": 0, "unit": null, '
        '"confidence": 0.9, "source_page": 1}], "timestamps": [], '
        '"signatures": [], "deviations": [], "notes": "", '
        '"confidence": 0.9, "source_page": 1}], '
        '"general_notes": [], "overall_confidence": 0.9}'
    )

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": BATCH_RECORD_SYSTEM_PROMPT + schema_hint,
        },
    ]

    user_content = ""
    if text:
        user_content = f"Document text:\n\n{text}"

    user_msg: dict[str, Any] = {
        "role": "user",
        "content": user_content or "Please analyze the attached images.",
    }
    if page_images:
        user_msg["images"] = [
            base64.b64encode(img_bytes).decode("utf-8")
            for _, img_bytes in page_images
        ]
    messages.append(user_msg)

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model_name,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {"num_predict": 4096},
            },
        )
        resp.raise_for_status()

    data = resp.json()
    content = data.get("message", {}).get("content", "")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Failed to parse Ollama JSON response: %s", content[:200])
        return BatchRecordExtraction(overall_confidence=0.0)

    try:
        return BatchRecordExtraction.model_validate(parsed)
    except Exception as e:
        logger.warning(
            "BatchRecordExtraction validation failed, attempting best-effort: %s", e
        )
        # Best-effort: extract what we can
        steps = []
        for raw_step in parsed.get("steps", []):
            if not isinstance(raw_step, dict):
                continue
            try:
                steps.append(ExtractedStep.model_validate(raw_step))
            except Exception:
                logger.debug("Skipping invalid step: %s", raw_step)

        return BatchRecordExtraction(
            document_title=parsed.get("document_title", ""),
            batch_id=parsed.get("batch_id"),
            product_name=parsed.get("product_name"),
            date=parsed.get("date"),
            steps=steps,
            general_notes=parsed.get("general_notes", []),
            overall_confidence=parsed.get("overall_confidence", 0.5),
        )


async def _extract_chunked(
    text: str,
    page_images: list[tuple[int, bytes]] | None,
    db: AsyncSession,
    org_id: UUID | None = None,
) -> BatchRecordExtraction:
    """Extract in batches of pages, then merge results."""
    if not page_images:
        # Text-only: single call should have worked, re-raise
        return await _extract_single_call(text, None, db, org_id)

    all_steps: list[ExtractedStep] = []
    all_notes: list[str] = []
    doc_title = ""
    batch_id = None
    product_name = None
    date = None
    total_confidence = 0.0
    chunk_count = 0

    # Split text by pages if possible (rough heuristic)
    text_lines = text.split("\n\n") if text else []

    for i in range(0, len(page_images), _CHUNK_SIZE):
        chunk_images = page_images[i : i + _CHUNK_SIZE]
        # Use corresponding text portion (rough split)
        chunk_text = ""
        if text_lines:
            start_pct = i / len(page_images) if page_images else 0
            end_pct = min(1.0, (i + _CHUNK_SIZE) / len(page_images))
            start_idx = int(start_pct * len(text_lines))
            end_idx = int(end_pct * len(text_lines))
            chunk_text = "\n\n".join(text_lines[start_idx:end_idx])

        chunk_result = await _extract_single_call(
            chunk_text, chunk_images, db, org_id,
        )

        all_steps.extend(chunk_result.steps)
        all_notes.extend(chunk_result.general_notes)
        total_confidence += chunk_result.overall_confidence
        chunk_count += 1

        # Keep first non-empty metadata
        if not doc_title and chunk_result.document_title:
            doc_title = chunk_result.document_title
        if not batch_id and chunk_result.batch_id:
            batch_id = chunk_result.batch_id
        if not product_name and chunk_result.product_name:
            product_name = chunk_result.product_name
        if not date and chunk_result.date:
            date = chunk_result.date

    avg_confidence = (
        total_confidence / chunk_count if chunk_count > 0 else 0.0
    )

    return BatchRecordExtraction(
        document_title=doc_title,
        batch_id=batch_id,
        product_name=product_name,
        date=date,
        steps=all_steps,
        general_notes=all_notes,
        overall_confidence=round(avg_confidence, 3),
    )


# ── Protocol mapping ─────────────────────────────────────────────────


async def map_steps_to_protocol(
    extraction: BatchRecordExtraction,
    protocol_graph: dict[str, Any],
    db: AsyncSession,
    org_id: UUID | None = None,
) -> list[StepMapping]:
    """Map extracted steps to protocol graph steps using LLM.

    Sends extracted step names + protocol step names + param schemas
    to the text model and gets back a structured mapping.
    """
    from app.services.ai_vision import _is_ollama_model, _get_ollama_model_name

    _, flat_steps, _ = _parse_graph_roles_and_steps(protocol_graph)
    if not flat_steps or not extraction.steps:
        return []

    model = await get_model("text", db, org_id=org_id)
    prompt = _build_mapping_prompt(extraction, flat_steps)
    system = (
        "You are a biotech protocol matching assistant. "
        "Map extracted batch record data to digital protocol steps."
    )

    # Ollama: use native API with JSON format
    if _is_ollama_model(model):
        config = await get_full_config("text", db, org_id=org_id)
        creds = config.get("credentials") or {}
        base_url = creds.get("base_url") or "http://localhost:11434"
        model_name = _get_ollama_model_name(model)

        schema_hint = (
            '\n\nReturn JSON: {"mappings": [{"extracted_step_index": 0, '
            '"extracted_step_name": "", "protocol_step_id": "", '
            '"protocol_step_name": "", "score": 0.9, '
            '"param_mappings": [{"extracted_param_index": 0, '
            '"extracted_label": "", "extracted_value": null, '
            '"extracted_unit": null, "schema_field_key": "", '
            '"schema_field_label": "", "confidence": 0.9}]}]}'
        )

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/api/chat",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system + schema_hint},
                        {"role": "user", "content": prompt},
                    ],
                    "format": "json",
                    "stream": False,
                    "options": {"num_predict": 4096},
                },
            )
            resp.raise_for_status()

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        try:
            parsed = json.loads(content)
            result = StepMappingResult.model_validate(parsed)
            return result.mappings
        except Exception as e:
            logger.warning("Ollama mapping parse failed: %s", e)
            return []

    # Cloud providers: pydantic-ai with structured output
    agent = Agent(
        model,
        output_type=StepMappingResult,
        instructions=system,
    )
    result = await agent.run(prompt)
    return result.output.mappings


# ── execution_data builder ───────────────────────────────────────────


def map_values_to_execution_data(
    finalized_mappings: list[dict[str, Any]],
    graph: dict[str, Any],
    user_id: UUID,
) -> dict[str, Any]:
    """Convert finalized step mappings to Run.execution_data format.

    Each mapped step gets status="completed" with results dict.
    Steps marked N/A get status="na" with na_reason.
    """
    execution_data: dict[str, Any] = {}

    for mapping in finalized_mappings:
        step_id = mapping["protocol_step_id"]

        # Handle N/A steps
        if mapping.get("na"):
            execution_data[step_id] = {
                "status": "na",
                "na_reason": mapping.get("na_reason", ""),
                "completed_by_user_id": str(user_id),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            continue

        # Build results from accepted values
        results: dict[str, Any] = {}
        for val in mapping.get("values", []):
            if val.get("accepted", False):
                results[val["schema_field_key"]] = val["value"]

        # Collect notes from extracted step
        notes = mapping.get("notes", "")

        execution_data[step_id] = {
            "status": "completed",
            "results": results,
            "notes": notes,
            "completed_by_user_id": str(user_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    return execution_data


# ── Background worker ────────────────────────────────────────────────


async def run_batch_record_extraction(
    import_id: UUID,
    db_url: str,
    org_id: UUID,
    protocol_id: UUID,
) -> None:
    """Background worker entry point for batch record extraction.

    Gets its own DB session, creates a BackgroundJob, extracts pages,
    runs LLM extraction + protocol mapping, and updates the import row.
    """
    from app.services.file_storage import FileStorageService

    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Load the import row
        result = await session.execute(
            select(BatchRecordImport).where(
                BatchRecordImport.id == import_id
            )
        )
        import_row = result.scalar_one_or_none()
        if not import_row:
            logger.error("BatchRecordImport %s not found", import_id)
            return

        # Create tracking job
        job = await BackgroundJobService.create(
            session, "batch_record_extract", "batch_record_import",
            import_id,
            input_data={"mime_type": import_row.mime_type},
        )
        await session.commit()

        try:
            # Stage 1: Extract pages
            await BackgroundJobService.update_progress(
                session, job, "extracting", "Extracting document pages",
                0, 1,
            )
            storage = FileStorageService()
            file_path = storage.resolve_path(import_row.file_path)
            text, page_images = await extract_batch_record_pages(
                file_path, import_row.mime_type, session, org_id,
            )
            import_row.page_count = len(page_images) or 1
            await session.commit()

            total_stages = 3  # extract, AI analysis, protocol mapping
            await BackgroundJobService.update_progress(
                session, job, "extracting", "Extracting document pages",
                1, total_stages,
            )

            # Stage 2: AI extraction
            await BackgroundJobService.update_progress(
                session, job, "analyzing", "AI analyzing batch record",
                1, total_stages,
            )
            extraction = await extract_batch_record_data(
                text, page_images, session, org_id,
            )
            import_row.extraction_result = extraction.model_dump()
            await session.commit()

            await BackgroundJobService.update_progress(
                session, job, "analyzing", "AI analyzing batch record",
                2, total_stages,
            )

            # Stage 3: Protocol mapping
            await BackgroundJobService.update_progress(
                session, job, "mapping",
                "Mapping to protocol",
                2, total_stages,
            )
            protocol_result = await session.execute(
                select(Protocol).where(Protocol.id == protocol_id)
            )
            protocol = protocol_result.scalar_one_or_none()

            step_mappings: list[StepMapping] = []
            if protocol and protocol.graph:
                step_mappings = await map_steps_to_protocol(
                    extraction, protocol.graph, session, org_id,
                )

            # Save results
            import_row.extraction_result = {
                **extraction.model_dump(),
                "step_mappings": [m.model_dump() for m in step_mappings],
            }
            import_row.status = BatchRecordImportStatus.REVIEW.value

            await BackgroundJobService.complete(
                session, job,
                output_data={
                    "page_count": import_row.page_count,
                    "steps_extracted": len(extraction.steps),
                    "steps_mapped": len(step_mappings),
                },
            )
            await session.commit()

            logger.info(
                "Batch record extraction complete for import %s: "
                "%d steps extracted, %d mapped",
                import_id,
                len(extraction.steps),
                len(step_mappings),
            )

        except Exception as exc:
            logger.exception(
                "Batch record extraction failed for import %s",
                import_id,
            )
            try:
                import_row.status = BatchRecordImportStatus.FAILED.value
                import_row.error_message = str(exc)[:500]
                await BackgroundJobService.fail(
                    session, job, str(exc)[:500]
                )
                await session.commit()
            except Exception:
                logger.exception("Failed to record error for import %s", import_id)

    await engine.dispose()
