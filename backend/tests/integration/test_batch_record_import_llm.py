"""LLM integration test for batch record import.

This test is SKIPPED in CI. Run manually to verify prompt quality:
    pytest tests/integration/test_batch_record_import_llm.py -m llm -v

Requires a running LLM (Ollama with llama3.2-vision:11b or cloud provider).
Saves extraction results as JSON artifacts for inspection.
"""

import json
import logging
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.batch_record_extractor import (
    BatchRecordExtraction,
    extract_batch_record_pages,
    extract_batch_record_data,
    map_steps_to_protocol,
)

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts"


@pytest.mark.llm
@pytest.mark.asyncio
async def test_extract_real_pdf_with_real_llm(db_session: AsyncSession):
    """Full extraction: real PDF + real LLM. Saves artifact."""
    pdf_path = FIXTURES_DIR / "sample_batch_record.pdf"
    assert pdf_path.exists(), f"Fixture not found: {pdf_path}"

    # Extract pages (real pymupdf)
    text, page_images = await extract_batch_record_pages(
        pdf_path, "application/pdf", db_session,
    )

    print(f"\n--- Page extraction ---")
    print(f"Text length: {len(text)} chars")
    print(f"Page images: {len(page_images)}")
    assert len(text) > 0, "PDF text extraction returned empty"
    assert len(page_images) == 2, "Expected 2 page images"

    # Extract structured data (real LLM)
    extraction = await extract_batch_record_data(
        text, page_images, db_session,
    )

    print(f"\n--- AI Extraction ---")
    print(f"Title: {extraction.document_title}")
    print(f"Batch ID: {extraction.batch_id}")
    print(f"Steps: {len(extraction.steps)}")
    print(f"Overall confidence: {extraction.overall_confidence}")
    for step in extraction.steps:
        print(f"  [{step.step_number}] {step.step_name} "
              f"(conf={step.confidence:.2f}, params={len(step.parameters)})")
        for p in step.parameters:
            print(f"    - {p.field_label}: {p.value} {p.unit or ''} "
                  f"(conf={p.confidence:.2f})")

    # Save artifact
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACTS_DIR / "batch_record_extraction_result.json"
    artifact_path.write_text(
        json.dumps(extraction.model_dump(), indent=2, default=str)
    )
    print(f"\nArtifact saved: {artifact_path}")

    # Non-strict sanity checks
    assert len(extraction.steps) > 0, "No steps extracted"
    assert extraction.overall_confidence > 0.0, "Zero confidence"


@pytest.mark.llm
@pytest.mark.asyncio
async def test_extract_and_map_to_protocol(db_session: AsyncSession):
    """Full extraction + protocol mapping: real PDF + real LLM."""
    pdf_path = FIXTURES_DIR / "sample_batch_record.pdf"

    text, page_images = await extract_batch_record_pages(
        pdf_path, "application/pdf", db_session,
    )
    extraction = await extract_batch_record_data(
        text, page_images, db_session,
    )

    # Protocol graph matching the fixture
    protocol_graph = {
        "nodes": [
            {
                "id": "node-buf",
                "type": "unitOp",
                "position": {"x": 0, "y": 0},
                "data": {
                    "label": "Buffer Preparation",
                    "paramSchema": {
                        "type": "object",
                        "properties": {
                            "ph_value": {"type": "number", "title": "pH Value"},
                            "temperature_c": {"type": "number", "title": "Temperature (°C)"},
                            "volume_ml": {"type": "number", "title": "Volume (mL)"},
                        },
                    },
                },
            },
            {
                "id": "node-cent",
                "type": "unitOp",
                "position": {"x": 200, "y": 0},
                "data": {
                    "label": "Centrifugation",
                    "paramSchema": {
                        "type": "object",
                        "properties": {
                            "speed_g": {"type": "number", "title": "Speed (g)"},
                            "duration_min": {"type": "number", "title": "Duration (min)"},
                            "temp_c": {"type": "number", "title": "Temperature (°C)"},
                        },
                    },
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "node-buf", "target": "node-cent"},
        ],
    }

    mappings = await map_steps_to_protocol(
        extraction, protocol_graph, db_session,
    )

    print(f"\n--- Protocol Mapping ---")
    print(f"Mappings: {len(mappings)}")
    for m in mappings:
        print(f"  [{m.extracted_step_index}] \"{m.extracted_step_name}\" "
              f"-> \"{m.protocol_step_name}\" (score={m.score:.2f})")
        for pm in m.param_mappings:
            print(f"    {pm.extracted_label} -> {pm.schema_field_key} "
                  f"(conf={pm.confidence:.2f})")

    # Save artifact
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACTS_DIR / "batch_record_mapping_result.json"
    artifact_path.write_text(
        json.dumps(
            {"extraction": extraction.model_dump(),
             "mappings": [m.model_dump() for m in mappings]},
            indent=2, default=str,
        )
    )
    print(f"\nArtifact saved: {artifact_path}")

    # Non-strict checks
    assert len(mappings) > 0, "No mappings produced"
