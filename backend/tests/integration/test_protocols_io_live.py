"""Live protocols.io API tests (F-0090).

Carry the ``live`` marker — excluded from the default CI run (`pytest -m
"not live"`) and auto-skipped when no access token is configured, so an
unconfigured CI environment never makes a network call.

Run explicitly:
    pytest -m live tests/integration/test_protocols_io_live.py -v

They call the connector module directly, so the external_protocols /
protocols_io feature flags need not be on — only an access token is required.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.ai.subagents.protocol_knowledgebase import protocols_io
from app.services.ai.subagents.protocol_knowledgebase.licenses import (
    classify_license,
)

pytestmark = pytest.mark.live

_CFG = settings.features.external_protocols.protocols_io
_NO_TOKEN = not _CFG.access_token.strip()
_SKIP_REASON = (
    "no protocols.io access token "
    "(BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN)"
)


@pytest.mark.skipif(_NO_TOKEN, reason=_SKIP_REASON)
async def test_live_search_returns_hits():
    """The v3 search endpoint accepts the token and returns parseable hits."""
    result = await protocols_io.search_protocols_io(
        "miniprep",
        access_token=_CFG.access_token,
        limit=5,
        timeout=_CFG.request_timeout_seconds,
    )
    assert result.total > 0, "expected at least one public protocols.io hit"
    first = result.hits[0]
    assert first.url.startswith("https://www.protocols.io/")
    assert first.title


@pytest.mark.skipif(_NO_TOKEN, reason=_SKIP_REASON)
async def test_live_fetch_round_trips_through_parser():
    """A live protocol fetch round-trips through the parser + license gate."""
    search = await protocols_io.search_protocols_io(
        "miniprep",
        access_token=_CFG.access_token,
        limit=5,
        timeout=_CFG.request_timeout_seconds,
    )
    assert search.hits, "search returned no hits — cannot fetch"

    payload = await protocols_io.fetch_protocols_io(
        search.hits[0].url,
        access_token=_CFG.access_token,
        timeout=_CFG.request_timeout_seconds,
    )
    # A live public protocol must parse cleanly — no genuine-failure error.
    assert payload.error is None, f"live fetch failed: {payload.error}"
    assert payload.title
    # The license must classify to a real verdict, not crash the parser.
    verdict = classify_license(payload.license)
    assert verdict.normalized
    # Import-safe protocols carry step text; restricted ones must not.
    if payload.import_allowed:
        assert payload.steps, "import-safe protocol parsed to 0 steps"
    else:
        assert payload.steps == []
