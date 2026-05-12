"""Pure parser for OpenWetWare wiki-text — fixture-driven, no HTTP."""

from pathlib import Path

from app.services.ai.subagents.protocol_knowledgebase.tools import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
    parse_openwetware_wikitext,
)

FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "openwetware"
    / "transformation_of_ecoli.wikitext"
).read_text()
SOURCE_URL = "https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli"


def test_parser_extracts_title():
    p = parse_openwetware_wikitext(
        FIXTURE,
        displaytitle="Sauer: Heat-shock transformation of competent E. coli",
        source_url=SOURCE_URL,
    )
    assert p.title == "Sauer: Heat-shock transformation of competent E. coli"
    assert p.source_url == SOURCE_URL


def test_parser_extracts_materials():
    p = parse_openwetware_wikitext(FIXTURE, "Sauer", SOURCE_URL)
    assert len(p.materials) == 4
    assert "competent DH5α" in p.materials[0]


def test_parser_extracts_steps_with_durations():
    p = parse_openwetware_wikitext(FIXTURE, "Sauer", SOURCE_URL)
    assert len(p.steps) == 7
    assert isinstance(p.steps[0], ExternalProtocolStep)
    # Step 1: "10 min" → 10
    assert p.steps[0].duration_min == 10
    # Step 2: "30 min" → 30
    assert p.steps[1].duration_min == 30
    # Step 3: "90 s" → ceil(90/60)=2 OR exact representation; we want minutes
    #         → spec says int|None; 90 s = 1.5 min → rounded to 2
    assert p.steps[2].duration_min == 2
    # Step 7: no duration → None
    assert p.steps[6].duration_min is None


def test_parser_extracts_notes_and_license():
    p = parse_openwetware_wikitext(FIXTURE, "Sauer", SOURCE_URL)
    assert "no-DNA control" in (p.notes or "")
    assert p.license == "CC BY-SA 3.0"
    assert "OpenWetWare contributors" in p.attribution


def test_parser_extracts_summary():
    p = parse_openwetware_wikitext(FIXTURE, "Sauer", SOURCE_URL)
    assert "CaCl" in p.summary and "42" in p.summary


def test_parser_handles_missing_sections_gracefully():
    minimal = "''Just a stub page with no sections.''"
    p = parse_openwetware_wikitext(minimal, "stub", SOURCE_URL)
    assert p.title == "stub"
    assert p.materials == []
    assert p.steps == []
    assert "stub" in p.summary
    assert p.license == "CC BY-SA 3.0"
