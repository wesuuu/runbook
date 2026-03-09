"""Tests for PDF helper functions in pdf_base.py."""

import pytest
from app.services.pdf_base import (
    _format_value,
    _build_param_sentence,
    _render_template,
    _get_param_title,
    _resolve_format,
    _get_editable_params,
    DEFAULT_FORMAT,
)


class TestFormatValue:
    """Test _format_value for various types."""

    def test_bool_true(self):
        assert _format_value(True) == "Yes"

    def test_bool_false(self):
        assert _format_value(False) == "No"

    def test_float_no_trailing_zeros(self):
        assert _format_value(37.0) == "37"

    def test_float_with_decimals(self):
        assert _format_value(37.5) == "37.5"

    def test_integer(self):
        assert _format_value(42) == "42"

    def test_string(self):
        assert _format_value("hello") == "hello"

    def test_list(self):
        assert _format_value([1, 2, 3]) == "1, 2, 3"

    def test_empty_list(self):
        assert _format_value([]) == ""

    def test_none(self):
        assert _format_value(None) == "None"


class TestGetParamTitle:
    """Test _get_param_title title extraction."""

    def test_title_from_schema(self):
        schema = {
            "properties": {
                "thaw_temp_c": {"type": "number", "title": "Thaw Temperature"},
            }
        }
        assert _get_param_title("thaw_temp_c", schema) == "Thaw Temperature"

    def test_fallback_snake_case(self):
        assert _get_param_title("thaw_temp_c", None) == "Thaw Temp C"

    def test_fallback_no_matching_prop(self):
        schema = {"properties": {"other_key": {"title": "Other"}}}
        assert _get_param_title("volume_ml", schema) == "Volume Ml"

    def test_empty_schema(self):
        assert _get_param_title("volume", {}) == "Volume"


class TestRenderTemplate:
    """Test _render_template placeholder substitution."""

    def test_basic_substitution(self):
        result = _render_template(
            "Set temperature to {{temp}} degrees",
            {"temp": 37},
        )
        assert result == "Set temperature to 37 degrees"

    def test_multiple_placeholders(self):
        result = _render_template(
            "Mix {{volume}} mL at {{speed}} RPM",
            {"volume": 500, "speed": 200},
        )
        assert result == "Mix 500 mL at 200 RPM"

    def test_missing_param_keeps_placeholder(self):
        result = _render_template(
            "Set {{temp}} and {{pressure}}",
            {"temp": 37},
        )
        assert result == "Set 37 and {{pressure}}"

    def test_none_value_keeps_placeholder(self):
        result = _render_template(
            "Set {{temp}} degrees",
            {"temp": None},
        )
        assert result == "Set {{temp}} degrees"

    def test_empty_string_keeps_placeholder(self):
        result = _render_template(
            "Set {{temp}} degrees",
            {"temp": ""},
        )
        assert result == "Set {{temp}} degrees"

    def test_no_params_returns_template(self):
        result = _render_template("No placeholders here", None)
        assert result == "No placeholders here"

    def test_no_placeholders_returns_unchanged(self):
        result = _render_template("No placeholders", {"temp": 37})
        assert result == "No placeholders"

    def test_bool_substitution(self):
        result = _render_template("Sterile: {{sterile}}", {"sterile": True})
        assert result == "Sterile: Yes"

    def test_float_substitution(self):
        result = _render_template("pH {{ph}}", {"ph": 7.0})
        assert result == "pH 7"


class TestBuildParamSentence:
    """Test _build_param_sentence prose generation."""

    def test_single_param(self):
        result = _build_param_sentence(
            {"volume": 500},
            {"properties": {"volume": {"title": "Volume"}}},
        )
        assert result == "Volume: 500."

    def test_multiple_params(self):
        result = _build_param_sentence(
            {"volume": 500, "speed": 200},
            {
                "properties": {
                    "volume": {"title": "Volume"},
                    "speed": {"title": "Speed"},
                }
            },
        )
        assert "Volume: 500" in result
        assert "Speed: 200" in result
        assert result.endswith(".")

    def test_none_params(self):
        assert _build_param_sentence(None, None) == ""

    def test_empty_params(self):
        assert _build_param_sentence({}, None) == ""

    def test_all_none_values(self):
        assert _build_param_sentence({"a": None, "b": None}, None) == ""

    def test_mixed_filled_and_none(self):
        result = _build_param_sentence(
            {"volume": 500, "temp": None},
            None,
        )
        assert "Volume" in result
        assert "Temp" not in result


class TestResolveFormat:
    """Test _resolve_format merging."""

    def test_none_returns_defaults(self):
        result = _resolve_format(None)
        assert result == DEFAULT_FORMAT

    def test_override_font_size(self):
        result = _resolve_format({"font_size": "large"})
        assert result["font_size"] == "large"
        assert result["font_family"] == "Helvetica"  # default preserved

    def test_none_values_ignored(self):
        result = _resolve_format({"font_size": None})
        assert result["font_size"] == "medium"  # default, not None

    def test_extra_keys_pass_through(self):
        result = _resolve_format({"custom_key": "value"})
        assert result["custom_key"] == "value"


class TestGetEditableParams:
    """Test _get_editable_params filtering."""

    def test_filters_xref_types(self):
        schema = {
            "properties": {
                "source_vessel": {
                    "type": "string",
                    "x-ref-type": "equipment",
                },
                "volume_ml": {"type": "number", "title": "Volume"},
            }
        }
        result = _get_editable_params(schema)
        assert len(result) == 1
        assert result[0][0] == "volume_ml"

    def test_no_schema_returns_empty(self):
        assert _get_editable_params(None) == []

    def test_empty_properties(self):
        assert _get_editable_params({"properties": {}}) == []

    def test_all_editable(self):
        schema = {
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "string"},
            }
        }
        result = _get_editable_params(schema)
        assert len(result) == 2

    def test_all_xref_returns_empty(self):
        schema = {
            "properties": {
                "vessel": {"type": "string", "x-ref-type": "equipment"},
            }
        }
        assert _get_editable_params(schema) == []
