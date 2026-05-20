"""Pure parser for protocols.io detail JSON — fixture-driven, no HTTP."""

import json
from pathlib import Path

from app.services.ai.subagents.protocol_knowledgebase.protocols_io import (
    parse_protocols_io_json,
)

FIX = Path(__file__).parent.parent / "fixtures" / "protocols_io"
SOURCE_URL = "https://www.protocols.io/view/plasmid-miniprep-alkaline-lysis-abc123"


def test_parser_import_safe_protocol():
    data = json.loads((FIX / "protocol_detail.json").read_text())
    p = parse_protocols_io_json(data, SOURCE_URL)
    assert p.title == "Plasmid Miniprep (Alkaline Lysis)"
    assert len(p.materials) >= 3
    assert len(p.steps) >= 5
    assert p.summary and "<p>" not in p.summary  # HTML stripped
    assert p.license == "CC BY 4.0"
    assert p.attribution.startswith("protocols.io — ")
    assert "Jane Doe" in p.attribution
    assert p.source_url == SOURCE_URL
    assert p.import_allowed is True
    assert p.error is None


def test_parser_license_restricted_protocol():
    """A restricted protocol parses to metadata only: import_allowed=False,
    error=None (restricted != failure), and NO step/material text copied."""
    data = json.loads((FIX / "protocol_detail_nc.json").read_text())
    p = parse_protocols_io_json(data, SOURCE_URL)
    assert p.import_allowed is False
    assert p.error is None
    assert p.steps == []
    assert p.materials == []
    assert p.license_note  # populated, explains why
    # The secret step text from the fixture must not leak into the payload.
    assert "SECRET" not in json.dumps(p.__dict__)


def test_parser_live_shape_no_license_field_treated_as_cc_by():
    """The live protocols.io v4 API returns NO ``license`` field at all.

    Per protocols.io platform policy every *published* public protocol is
    released under CC-BY 4.0, so a non-zero ``published_on`` timestamp is
    the authoritative license signal. The parser must treat such a payload
    as import-safe and actually extract its Draft.js steps — not fail
    closed to a metadata-only stub. Regression for the live-API mismatch
    found in F-0090 QA. The fixture is a trimmed real v4 response.
    """
    data = json.loads((FIX / "protocol_detail_live_shape.json").read_text())
    assert "license" not in data["payload"]  # fixture mirrors the live shape
    p = parse_protocols_io_json(data, SOURCE_URL)
    assert p.import_allowed is True
    assert p.license.startswith("CC")
    assert len(p.steps) >= 1  # Draft.js steps extracted, not skipped
    assert p.summary and "{" not in p.summary  # Draft.js decoded to plain text
    assert p.error is None


def test_parser_unpublished_no_license_fails_closed():
    """A payload with neither a ``license`` field nor a ``published_on``
    timestamp is not verifiable published public content — the parser must
    still fail closed (import_allowed=False, no step text copied)."""
    data = json.loads((FIX / "protocol_detail_live_shape.json").read_text())
    data["payload"].pop("published_on", None)
    p = parse_protocols_io_json(data, SOURCE_URL)
    assert p.import_allowed is False
    assert p.steps == []
