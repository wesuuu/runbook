"""Unit tests for F-0086 produces_lot exposure in the docx Jinja context."""

import pytest

from app.services.protocols.template_engine import KNOWN_VARIABLES, build_context


def test_produces_lot_is_a_known_template_variable():
    assert "produces_lot" in KNOWN_VARIABLES


def test_build_context_defaults_produces_lot_to_false():
    """When no produces_lot kwarg is passed, the context exposes False."""
    ctx, _ = build_context(protocol_name="P")
    assert "produces_lot" in ctx
    assert ctx["produces_lot"] is False


def test_build_context_passes_produces_lot_through_true():
    """The rendered context exposes produces_lot as a bool when True."""
    ctx, _ = build_context(protocol_name="P", produces_lot=True)
    assert ctx["produces_lot"] is True


def test_build_context_coerces_produces_lot_to_bool():
    """Non-bool truthy/falsy values are coerced to bool."""
    ctx_true, _ = build_context(protocol_name="P", produces_lot="yes")
    assert ctx_true["produces_lot"] is True

    ctx_false, _ = build_context(protocol_name="P", produces_lot=0)
    assert ctx_false["produces_lot"] is False
