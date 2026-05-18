"""Unit tests for batch record extraction service."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.batch.batch_record_extractor import (
    BatchRecordExtraction,
    ExtractedDeviation,
    ExtractedParameterValue,
    ExtractedSignature,
    ExtractedStep,
    ExtractedTimestamp,
    ParamMapping,
    StepMapping,
    StepMappingResult,
    _extract_chunked,
    extract_batch_record_data,
    map_values_to_execution_data,
)

# ── Pydantic model validation ───────────────────────────────────────


class TestExtractionModels:
    def test_extracted_parameter_value_valid(self):
        v = ExtractedParameterValue(
            field_label="pH",
            value=7.2,
            unit="pH",
            confidence=0.95,
            source_page=1,
        )
        assert v.field_label == "pH"
        assert v.value == 7.2
        assert v.confidence == 0.95

    def test_extracted_parameter_value_string_value(self):
        v = ExtractedParameterValue(
            field_label="Color",
            value="amber",
            confidence=0.8,
        )
        assert v.value == "amber"
        assert v.unit is None
        assert v.source_page is None

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ExtractedParameterValue(
                field_label="pH",
                value=7.0,
                confidence=1.5,
            )
        with pytest.raises(Exception):
            ExtractedParameterValue(
                field_label="pH",
                value=7.0,
                confidence=-0.1,
            )

    def test_extracted_step_with_all_fields(self):
        step = ExtractedStep(
            step_name="Buffer Prep",
            step_number=1,
            parameters=[
                ExtractedParameterValue(
                    field_label="pH",
                    value=7.4,
                    confidence=0.9,
                ),
            ],
            timestamps=[
                ExtractedTimestamp(
                    value="2026-01-15T08:30:00",
                    label="Start",
                    confidence=0.85,
                ),
            ],
            signatures=[
                ExtractedSignature(
                    initials_or_name="JKL",
                    role="Operator",
                    confidence=0.9,
                ),
            ],
            deviations=[
                ExtractedDeviation(
                    description="Slight foam observed",
                    severity="minor",
                    confidence=0.7,
                ),
            ],
            notes="Mixed for 30 min",
            confidence=0.88,
            source_page=2,
        )
        assert step.step_name == "Buffer Prep"
        assert len(step.parameters) == 1
        assert len(step.timestamps) == 1
        assert len(step.signatures) == 1
        assert len(step.deviations) == 1

    def test_batch_record_extraction_empty_steps(self):
        extraction = BatchRecordExtraction(
            document_title="Batch 001",
            overall_confidence=0.0,
        )
        assert extraction.steps == []
        assert extraction.general_notes == []

    def test_batch_record_extraction_full(self):
        extraction = BatchRecordExtraction(
            document_title="Process Record - Batch 42",
            batch_id="LOT-2026-042",
            product_name="mAb-X",
            date="2026-01-15",
            steps=[
                ExtractedStep(
                    step_name="Seeding",
                    parameters=[
                        ExtractedParameterValue(
                            field_label="Cell Density",
                            value=0.5e6,
                            unit="cells/mL",
                            confidence=0.92,
                            source_page=1,
                        ),
                    ],
                    confidence=0.9,
                ),
            ],
            overall_confidence=0.87,
        )
        assert extraction.batch_id == "LOT-2026-042"
        assert len(extraction.steps) == 1


class TestStepMappingModels:
    def test_step_mapping_valid(self):
        m = StepMapping(
            extracted_step_index=0,
            extracted_step_name="Buffer Prep",
            protocol_step_id="node-abc123",
            protocol_step_name="Buffer Preparation",
            score=0.85,
            param_mappings=[
                ParamMapping(
                    extracted_param_index=0,
                    extracted_label="pH",
                    extracted_value=7.4,
                    schema_field_key="ph_value",
                    schema_field_label="pH Value",
                    confidence=0.9,
                ),
            ],
        )
        assert m.score == 0.85
        assert len(m.param_mappings) == 1

    def test_step_mapping_result(self):
        result = StepMappingResult(
            mappings=[
                StepMapping(
                    extracted_step_index=0,
                    extracted_step_name="Step 1",
                    protocol_step_id="node-1",
                    protocol_step_name="Step One",
                    score=0.9,
                ),
            ]
        )
        assert len(result.mappings) == 1


# ── map_values_to_execution_data ─────────────────────────────────────


class TestMapValuesToExecutionData:
    def test_basic_mapping(self):
        user_id = uuid.uuid4()
        mappings = [
            {
                "protocol_step_id": "node-1",
                "values": [
                    {
                        "schema_field_key": "ph_value",
                        "value": 7.2,
                        "accepted": True,
                    },
                    {
                        "schema_field_key": "temperature",
                        "value": 37,
                        "accepted": True,
                    },
                ],
            },
        ]

        result = map_values_to_execution_data(mappings, {}, user_id)

        assert "node-1" in result
        assert result["node-1"]["status"] == "completed"
        assert result["node-1"]["results"]["ph_value"] == 7.2
        assert result["node-1"]["results"]["temperature"] == 37
        assert result["node-1"]["completed_by_user_id"] == str(user_id)

    def test_rejected_values_excluded(self):
        user_id = uuid.uuid4()
        mappings = [
            {
                "protocol_step_id": "node-1",
                "values": [
                    {
                        "schema_field_key": "ph_value",
                        "value": 7.2,
                        "accepted": True,
                    },
                    {
                        "schema_field_key": "bad_reading",
                        "value": 999,
                        "accepted": False,
                    },
                ],
            },
        ]

        result = map_values_to_execution_data(mappings, {}, user_id)

        assert "ph_value" in result["node-1"]["results"]
        assert "bad_reading" not in result["node-1"]["results"]

    def test_na_status_with_reason(self):
        user_id = uuid.uuid4()
        mappings = [
            {
                "protocol_step_id": "node-skipped",
                "na": True,
                "na_reason": "Run ended early — batch failed QC",
            },
        ]

        result = map_values_to_execution_data(mappings, {}, user_id)

        assert result["node-skipped"]["status"] == "na"
        assert "batch failed QC" in result["node-skipped"]["na_reason"]
        assert result["node-skipped"]["completed_by_user_id"] == str(user_id)

    def test_na_without_reason(self):
        user_id = uuid.uuid4()
        mappings = [
            {
                "protocol_step_id": "node-empty",
                "na": True,
            },
        ]

        result = map_values_to_execution_data(mappings, {}, user_id)
        assert result["node-empty"]["na_reason"] == ""

    def test_mixed_completed_and_na(self):
        user_id = uuid.uuid4()
        mappings = [
            {
                "protocol_step_id": "node-1",
                "values": [
                    {"schema_field_key": "ph", "value": 7.0, "accepted": True},
                ],
            },
            {
                "protocol_step_id": "node-2",
                "na": True,
                "na_reason": "Not performed",
            },
        ]

        result = map_values_to_execution_data(mappings, {}, user_id)

        assert result["node-1"]["status"] == "completed"
        assert result["node-2"]["status"] == "na"

    def test_empty_mappings(self):
        result = map_values_to_execution_data([], {}, uuid.uuid4())
        assert result == {}

    def test_step_with_notes(self):
        user_id = uuid.uuid4()
        mappings = [
            {
                "protocol_step_id": "node-1",
                "values": [],
                "notes": "Slight foam observed during mixing",
            },
        ]

        result = map_values_to_execution_data(mappings, {}, user_id)
        assert result["node-1"]["notes"] == "Slight foam observed during mixing"

    def test_timestamp_present(self):
        user_id = uuid.uuid4()
        mappings = [
            {
                "protocol_step_id": "node-1",
                "values": [],
            },
        ]

        result = map_values_to_execution_data(mappings, {}, user_id)
        # Should have a valid ISO timestamp
        ts = result["node-1"]["timestamp"]
        datetime.fromisoformat(ts)  # Should not raise


# ── Extraction paths (mocked LLM) ───────────────────────────────────


class TestExtractBatchRecordData:
    async def test_single_call_success(self):
        mock_extraction = BatchRecordExtraction(
            document_title="Test",
            steps=[
                ExtractedStep(
                    step_name="Step 1",
                    confidence=0.9,
                    parameters=[
                        ExtractedParameterValue(
                            field_label="pH",
                            value=7.0,
                            confidence=0.95,
                        ),
                    ],
                ),
            ],
            overall_confidence=0.9,
        )

        with patch(
            "app.services.batch.batch_record_extractor._extract_single_call",
            new_callable=lambda: AsyncMock(return_value=mock_extraction),
        ):
            result = await extract_batch_record_data(
                "some text",
                [(1, b"fake_png")],
                None,
                None,
            )

        assert result.document_title == "Test"
        assert len(result.steps) == 1
        assert result.steps[0].parameters[0].value == 7.0

    async def test_falls_back_to_chunked_on_context_overflow(self):
        mock_extraction = BatchRecordExtraction(
            document_title="Chunked",
            steps=[
                ExtractedStep(step_name="S1", confidence=0.8),
            ],
            overall_confidence=0.8,
        )

        call_count = 0

        async def mock_single_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("context length exceeded")
            return mock_extraction

        with patch(
            "app.services.batch.batch_record_extractor._extract_single_call",
            side_effect=mock_single_call,
        ):
            result = await extract_batch_record_data(
                "text",
                [(1, b"pg1"), (2, b"pg2")],
                None,
                None,
            )

        assert result.document_title == "Chunked"
        assert call_count > 1  # First call failed, then chunked calls

    async def test_non_context_error_propagates(self):
        with patch(
            "app.services.batch.batch_record_extractor._extract_single_call",
            new_callable=lambda: AsyncMock(side_effect=ValueError("some other error")),
        ):
            with pytest.raises(ValueError, match="some other error"):
                await extract_batch_record_data(
                    "text",
                    [(1, b"pg1")],
                    None,
                    None,
                )


class TestExtractChunked:
    async def test_merges_steps_from_chunks(self):
        chunk1 = BatchRecordExtraction(
            document_title="Doc",
            batch_id="LOT-1",
            steps=[
                ExtractedStep(step_name="Step A", confidence=0.9, source_page=1),
            ],
            overall_confidence=0.9,
        )
        chunk2 = BatchRecordExtraction(
            steps=[
                ExtractedStep(step_name="Step B", confidence=0.85, source_page=8),
            ],
            overall_confidence=0.85,
        )

        call_idx = 0

        async def mock_single(*args, **kwargs):
            nonlocal call_idx
            call_idx += 1
            return chunk1 if call_idx == 1 else chunk2

        # Need > _CHUNK_SIZE (5) pages to trigger multiple chunks
        pages = [(i, f"page{i}".encode()) for i in range(1, 11)]
        text = "\n\n".join(f"text page {i}" for i in range(1, 11))

        with patch(
            "app.services.batch.batch_record_extractor._extract_single_call",
            side_effect=mock_single,
        ):
            result = await _extract_chunked(text, pages, None, None)

        assert len(result.steps) == 2
        assert result.steps[0].step_name == "Step A"
        assert result.steps[1].step_name == "Step B"
        assert result.document_title == "Doc"
        assert result.batch_id == "LOT-1"
        assert 0.85 <= result.overall_confidence <= 0.9

    async def test_empty_pages_returns_empty(self):
        mock_result = BatchRecordExtraction(overall_confidence=0.0)

        with patch(
            "app.services.batch.batch_record_extractor._extract_single_call",
            new_callable=lambda: AsyncMock(return_value=mock_result),
        ):
            result = await _extract_chunked("", [], None, None)

        # With no page_images, falls through to single call
        assert result.overall_confidence == 0.0
