"""Tests for flag-aware chat-agent system-prompt rendering."""

import pytest

from app.services.ai.chat_agent import render_chat_agent_prompt


def test_both_sources_enabled_mentions_both():
    out = render_chat_agent_prompt(
        external_master_enabled=True,
        openwetware_enabled=True,
        protocols_io_enabled=True,
    )
    assert "OpenWetWare" in out
    assert "protocols.io" in out


def test_only_openwetware_mentions_only_openwetware():
    out = render_chat_agent_prompt(
        external_master_enabled=True,
        openwetware_enabled=True,
        protocols_io_enabled=False,
    )
    assert "OpenWetWare" in out
    assert "protocols.io" not in out


def test_only_protocols_io_mentions_only_protocols_io():
    out = render_chat_agent_prompt(
        external_master_enabled=True,
        openwetware_enabled=False,
        protocols_io_enabled=True,
    )
    assert "protocols.io" in out
    assert "OpenWetWare" not in out


def test_master_flag_off_drops_protocol_knowledgebase_section():
    out = render_chat_agent_prompt(
        external_master_enabled=False,
        openwetware_enabled=True,
        protocols_io_enabled=True,
    )
    assert "OpenWetWare" not in out
    assert "protocols.io" not in out
    assert "protocol_knowledgebase" not in out


def test_neither_sub_source_enabled_drops_section():
    out = render_chat_agent_prompt(
        external_master_enabled=True,
        openwetware_enabled=False,
        protocols_io_enabled=False,
    )
    assert "OpenWetWare" not in out
    assert "protocols.io" not in out
    assert "protocol_knowledgebase" not in out


def test_cache_key_changes_when_external_protocols_flag_flips(monkeypatch):
    """Flipping a flag must produce a different cache key so the next
    build_chat_agent call re-renders the prompt instead of returning
    the cached agent with the stale rendering."""
    from app.services.ai.chat_agent import _cache_key
    from app.core.config import settings

    monkeypatch.setattr(settings.features.external_protocols.protocols_io, "enabled", False)
    key_off = _cache_key("m1", "m2", "m3", "m4", "m5", 8192)
    monkeypatch.setattr(settings.features.external_protocols.protocols_io, "enabled", True)
    key_on = _cache_key("m1", "m2", "m3", "m4", "m5", 8192)
    assert key_off != key_on
