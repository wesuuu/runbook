"""Static assertions over the new-protocol SKILL.md content."""

from pathlib import Path

SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "app/services/ai/skills/new-protocol/SKILL.md"
)


def test_skill_mentions_both_external_sources():
    """Both OpenWetWare and protocols.io must be named so the parent
    agent advertises the full set when asked 'what sources can you
    derive protocols from?'."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "OpenWetWare" in text
    assert "protocols.io" in text
