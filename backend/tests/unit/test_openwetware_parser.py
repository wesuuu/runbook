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


# ─── Real-world OpenWetWare page (Agarose gel electrophoresis) ─────────────────
# Section names on real OWW pages aren't bare synonyms — they're things like
# "General Procedure", "Casting Gels", "Phusion". The parser must match via
# substring (heading contains a synonym word) and fall back to scanning the
# whole page when no section matches.

AGAROSE_FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "openwetware"
    / "agarose_gel_electrophoresis.wikitext"
).read_text()
AGAROSE_URL = "https://openwetware.org/wiki/Agarose_gel_electrophoresis"


def test_parser_matches_general_procedure_section_by_substring():
    p = parse_openwetware_wikitext(
        AGAROSE_FIXTURE,
        displaytitle="Agarose gel electrophoresis",
        source_url=AGAROSE_URL,
    )
    # "General Procedure" contains "procedure" → must match.
    assert len(p.steps) >= 5
    texts = [s.text for s in p.steps]
    assert any("Cast a gel" in t for t in texts)
    assert any("Image the gel" in t for t in texts)


def test_parser_extracts_summary_from_preamble():
    p = parse_openwetware_wikitext(
        AGAROSE_FIXTURE,
        displaytitle="Agarose gel electrophoresis",
        source_url=AGAROSE_URL,
    )
    assert "separate DNA" in p.summary or "agarose" in p.summary.lower()


def test_parser_fallback_when_no_section_matches():
    # No procedure-flavoured heading anywhere, but a numbered list exists.
    wt = (
        "Some intro paragraph.\n\n"
        "== Phusion ==\n"
        "# Add primers\n"
        "# Add template\n"
        "# Run PCR\n"
    )
    p = parse_openwetware_wikitext(wt, "Cloning Protocol", AGAROSE_URL)
    # No section name matches "procedure/method/protocol/steps/instructions",
    # so the parser must fall back to gathering top-level # items across the
    # whole page rather than returning steps=[].
    assert len(p.steps) == 3
    assert p.steps[0].text == "Add primers"


# ─── Real-world: "Preparing chemically competent cells" ──────────────────────
# The procedure section is named "Preparation" (no substring match against the
# synonym set). The page contains `#*` sub-bullets nested under numbered steps
# and a `<biblio>` block whose entries start with `#`. The parser must:
#   1. Match the procedure via fallback (whole-page `#` scan).
#   2. NOT treat `#*` sub-bullets as top-level steps.
#   3. NOT pull `<biblio>` entries (`#chung ...`) in as steps.

COMPETENT_FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "openwetware"
    / "preparing_chemically_competent_cells.wikitext"
).read_text()
COMPETENT_URL = "https://openwetware.org/wiki/Preparing_chemically_competent_cells"


def test_parser_skips_sub_bullets_and_biblio():
    p = parse_openwetware_wikitext(
        COMPETENT_FIXTURE,
        displaytitle="Preparing chemically competent cells",
        source_url=COMPETENT_URL,
    )
    texts = [s.text for s in p.steps]
    # No biblio entries should leak in as steps.
    assert not any(
        "pmid=" in t for t in texts
    ), f"Biblio entries leaked as steps: {[t for t in texts if 'pmid=' in t]}"
    # No `#*` sub-bullet content should be a top-level step. Look for
    # signature substrings unique to the sub-bullets on this page.
    assert not any("PCR tubes also work" in t for t in texts)
    assert not any("Higher concentrations of cells" in t for t in texts)
    assert not any("original paper" in t for t in texts)
    # The real numbered steps must still be there.
    assert any(t.startswith("Grow a 5 mL") for t in texts)
    assert any("Centrifuge for 10 min" in t for t in texts)
    assert any(t.startswith("Add 100") and "aliquot" in t for t in texts)
    # The page has exactly 9 numbered (`#`) top-level steps in source order.
    assert len(p.steps) == 9, f"Expected 9 top-level steps, got {len(p.steps)}: {texts}"
