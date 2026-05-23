"""Tests for source_label population on fetch tools."""

from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
)


def test_payload_has_source_label_field_with_default():
    """source_label defaults to empty string so existing test fixtures
    that construct payloads without it keep working."""
    p = ExternalProtocolPayload(title="t", source_url="u", summary="s")
    assert p.source_label == ""
