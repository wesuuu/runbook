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
