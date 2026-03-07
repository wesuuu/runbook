import os
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from pydantic_ai.models.test import TestModel

from app.services.ai_vision import (
    ImageAnalysisResult,
    ExtractedValue,
    analyze_image,
    continue_conversation,
    build_system_prompt,
    build_conversation_prompt,
    create_vision_agent,
    _guess_mime,
    _format_history,
)

SAMPLE_PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "viable_cell_density": {
            "type": "number",
            "title": "Viable Cell Density",
            "unit": "cells/mL",
        },
        "viability_percent": {
            "type": "number",
            "title": "Viability",
            "unit": "%",
        },
        "media_source": {
            "type": "string",
            "title": "Media Source",
            "x-ref-type": "media_prep",
        },
    },
}


# ── Prompt Building ──────────────────────────────────────────────────


class TestBuildSystemPrompt:
    def test_includes_step_name(self):
        prompt = build_system_prompt("Cell Count", SAMPLE_PARAM_SCHEMA)
        assert "Cell Count" in prompt

    def test_includes_field_keys(self):
        prompt = build_system_prompt("Cell Count", SAMPLE_PARAM_SCHEMA)
        assert "viable_cell_density" in prompt
        assert "viability_percent" in prompt

    def test_includes_field_labels(self):
        prompt = build_system_prompt("Cell Count", SAMPLE_PARAM_SCHEMA)
        assert "Viable Cell Density" in prompt
        assert "Viability" in prompt

    def test_includes_units(self):
        prompt = build_system_prompt("Cell Count", SAMPLE_PARAM_SCHEMA)
        assert "cells/mL" in prompt
        assert "%" in prompt

    def test_skips_ref_type_fields(self):
        prompt = build_system_prompt("Cell Count", SAMPLE_PARAM_SCHEMA)
        assert "media_source" not in prompt
        assert "x-ref-type" not in prompt

    def test_empty_schema(self):
        prompt = build_system_prompt("Empty Step", {})
        assert "Empty Step" in prompt
        assert "no specific fields defined" in prompt

    def test_schema_without_properties(self):
        prompt = build_system_prompt("Basic Step", {"type": "object"})
        assert "Basic Step" in prompt


class TestBuildConversationPrompt:
    def test_includes_step_name(self):
        prompt = build_conversation_prompt("Cell Count", SAMPLE_PARAM_SCHEMA)
        assert "Cell Count" in prompt

    def test_includes_follow_up_context(self):
        prompt = build_conversation_prompt("Cell Count", SAMPLE_PARAM_SCHEMA)
        assert "follow-up" in prompt.lower()


# ── Helper functions ──────────────────────────────────────────────────


class TestGuessMime:
    def test_jpg(self):
        assert _guess_mime("/path/to/image.jpg") == "image/jpeg"

    def test_jpeg(self):
        assert _guess_mime("/path/to/image.jpeg") == "image/jpeg"

    def test_png(self):
        assert _guess_mime("/path/to/image.png") == "image/png"

    def test_webp(self):
        assert _guess_mime("/path/to/image.webp") == "image/webp"

    def test_unknown_defaults_to_jpeg(self):
        assert _guess_mime("/path/to/image.bmp") == "image/jpeg"


class TestFormatHistory:
    def test_formats_messages(self):
        messages = [
            {"role": "assistant", "content": "I see a cell count"},
            {"role": "user", "content": "Yes, that's correct"},
        ]
        result = _format_history(messages)
        assert "ASSISTANT: I see a cell count" in result
        assert "USER: Yes, that's correct" in result

    def test_empty_history(self):
        assert _format_history([]) == ""


# ── Agent creation ────────────────────────────────────────────────────


class TestCreateVisionAgent:
    def test_creates_agent_with_output_type(self):
        agent = create_vision_agent("test prompt", model="test")
        assert agent is not None

    def test_agent_produces_structured_output(self):
        agent = create_vision_agent("test prompt", model="test")
        result = agent.run_sync(
            "test",
            model=TestModel(
                custom_output_args={
                    "message": "Test result",
                    "extracted_values": [],
                    "needs_clarification": False,
                }
            ),
        )
        assert isinstance(result.output, ImageAnalysisResult)
        assert result.output.message == "Test result"


# ── analyze_image ─────────────────────────────────────────────────────


class TestAnalyzeImage:
    @pytest.fixture
    def test_image(self, tmp_path: Path) -> str:
        """Create a test image file."""
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-data")
        return str(img_path)

    @pytest.mark.asyncio
    async def test_returns_extracted_values(
        self, test_image: str, db_session
    ):
        mock_output = {
            "message": "I can see a cell counting display showing viable cell density of 2.4 million cells per mL and viability of 96.2%.",
            "extracted_values": [
                {
                    "field_key": "viable_cell_density",
                    "field_label": "Viable Cell Density",
                    "value": 2400000.0,
                    "unit": "cells/mL",
                    "confidence": 0.95,
                },
                {
                    "field_key": "viability_percent",
                    "field_label": "Viability",
                    "value": 96.2,
                    "unit": "%",
                    "confidence": 0.90,
                },
            ],
            "needs_clarification": False,
        }

        test_model = TestModel(custom_output_args=mock_output)
        result = await analyze_image(
            image_path=test_image,
            step_name="Cell Count",
            param_schema=SAMPLE_PARAM_SCHEMA,
            db=db_session,
            model_override=test_model,
        )

        assert isinstance(result, ImageAnalysisResult)
        assert len(result.extracted_values) == 2
        assert result.extracted_values[0].field_key == "viable_cell_density"
        assert result.extracted_values[0].value == 2400000.0
        assert result.extracted_values[1].field_key == "viability_percent"
        assert result.needs_clarification is False

    @pytest.mark.asyncio
    async def test_returns_clarification_when_uncertain(
        self, test_image: str, db_session
    ):
        mock_output = {
            "message": "I can see a number on the display but I'm not sure which measurement it corresponds to. Is this the viable cell density or the total cell count?",
            "extracted_values": [
                {
                    "field_key": "viable_cell_density",
                    "field_label": "Viable Cell Density",
                    "value": 1800000.0,
                    "unit": "cells/mL",
                    "confidence": 0.4,
                },
            ],
            "needs_clarification": True,
        }

        test_model = TestModel(custom_output_args=mock_output)
        result = await analyze_image(
            image_path=test_image,
            step_name="Cell Count",
            param_schema=SAMPLE_PARAM_SCHEMA,
            db=db_session,
            model_override=test_model,
        )

        assert result.needs_clarification is True
        assert len(result.extracted_values) == 1
        assert result.extracted_values[0].confidence == 0.4

    @pytest.mark.asyncio
    async def test_empty_extraction(self, test_image: str, db_session):
        mock_output = {
            "message": "The image is blurry and I cannot read any values from the display.",
            "extracted_values": [],
            "needs_clarification": True,
        }

        test_model = TestModel(custom_output_args=mock_output)
        result = await analyze_image(
            image_path=test_image,
            step_name="Cell Count",
            param_schema=SAMPLE_PARAM_SCHEMA,
            db=db_session,
            model_override=test_model,
        )

        assert len(result.extracted_values) == 0
        assert result.needs_clarification is True


# ── continue_conversation ─────────────────────────────────────────────


class TestContinueConversation:
    @pytest.fixture
    def test_image(self, tmp_path: Path) -> str:
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-data")
        return str(img_path)

    @pytest.mark.asyncio
    async def test_uses_conversation_history(
        self, test_image: str, db_session
    ):
        prev_messages = [
            {
                "role": "assistant",
                "content": "I see a value of 2.4M. Is this the viable cell density?",
            },
        ]

        mock_output = {
            "message": "Great, I've confirmed the viable cell density as 2.4 million cells/mL.",
            "extracted_values": [
                {
                    "field_key": "viable_cell_density",
                    "field_label": "Viable Cell Density",
                    "value": 2400000.0,
                    "unit": "cells/mL",
                    "confidence": 0.98,
                },
            ],
            "needs_clarification": False,
        }

        test_model = TestModel(custom_output_args=mock_output)
        result = await continue_conversation(
            image_path=test_image,
            step_name="Cell Count",
            param_schema=SAMPLE_PARAM_SCHEMA,
            messages=prev_messages,
            user_reply="Yes, that's the viable cell density",
            db=db_session,
            model_override=test_model,
        )

        assert result.needs_clarification is False
        assert result.extracted_values[0].confidence == 0.98
        assert result.extracted_values[0].field_key == "viable_cell_density"

    @pytest.mark.asyncio
    async def test_multi_turn_refinement(
        self, test_image: str, db_session
    ):
        prev_messages = [
            {"role": "assistant", "content": "I see two values: 2.4M and 96.2%."},
            {"role": "user", "content": "The 2.4M is viable cell density"},
            {
                "role": "assistant",
                "content": "Got it. And the 96.2%—is that the viability?",
            },
        ]

        mock_output = {
            "message": "Both values confirmed.",
            "extracted_values": [
                {
                    "field_key": "viable_cell_density",
                    "field_label": "Viable Cell Density",
                    "value": 2400000.0,
                    "unit": "cells/mL",
                    "confidence": 0.98,
                },
                {
                    "field_key": "viability_percent",
                    "field_label": "Viability",
                    "value": 96.2,
                    "unit": "%",
                    "confidence": 0.98,
                },
            ],
            "needs_clarification": False,
        }

        test_model = TestModel(custom_output_args=mock_output)
        result = await continue_conversation(
            image_path=test_image,
            step_name="Cell Count",
            param_schema=SAMPLE_PARAM_SCHEMA,
            messages=prev_messages,
            user_reply="Yes, that's the viability percentage",
            db=db_session,
            model_override=test_model,
        )

        assert len(result.extracted_values) == 2
        assert result.needs_clarification is False


# ── ExtractedValue validation ─────────────────────────────────────────


class TestExtractedValueModel:
    def test_valid_value(self):
        ev = ExtractedValue(
            field_key="viable_cell_density",
            field_label="Viable Cell Density",
            value=2400000.0,
            unit="cells/mL",
            confidence=0.95,
        )
        assert ev.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ExtractedValue(
                field_key="test",
                field_label="Test",
                value=1.0,
                confidence=1.5,  # Over 1.0
            )

    def test_string_value(self):
        ev = ExtractedValue(
            field_key="sample_id",
            field_label="Sample ID",
            value="BATCH-2024-001",
            confidence=0.99,
        )
        assert ev.value == "BATCH-2024-001"

    def test_int_value(self):
        ev = ExtractedValue(
            field_key="count",
            field_label="Count",
            value=42,
            confidence=0.9,
        )
        assert ev.value == 42
