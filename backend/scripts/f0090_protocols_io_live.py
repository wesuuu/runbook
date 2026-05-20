"""F-0090 live smoke test for the protocols.io connector.

Usage (from backend/, venv active):
    python scripts/f0090_protocols_io_live.py [--query QUERY] [--url URL] [--raw]

Hits the real protocols.io v3 search + v4 detail endpoints with the configured
access token, then runs the F-0090 connector + parser + license gate over the
live response and prints the result. With --raw it also dumps the raw v4
detail JSON so the Task 6 parser fixtures can be confirmed against the live
shape.

Calls the connector module directly, so it works regardless of the
external_protocols / protocols_io feature flags — it only needs a token:
    BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN

This is a manual harness — never run in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

from app.core.config import settings
from app.services.ai.subagents.protocol_knowledgebase import protocols_io
from app.services.ai.subagents.protocol_knowledgebase.licenses import (
    classify_license,
)


def _config() -> object:
    return settings.features.external_protocols.protocols_io


async def _dump_raw_detail(url: str, token: str, timeout: float) -> None:
    """Print the raw v4 detail JSON — the executable form of Task 6 Step 0.

    Uses the connector's private id/URL helpers deliberately: this script is a
    sibling of the connector and exists to confirm the very shape the parser
    expects.
    """
    protocol_id = protocols_io._protocol_id_from_url(url)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{protocols_io._DETAIL_URL}/{protocol_id}",
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
    print(
        "--- raw v4 detail JSON "
        "(compare to tests/fixtures/protocols_io/protocol_detail.json) ---"
    )
    print(json.dumps(resp.json(), indent=2))
    print("--- end raw JSON ---\n")


async def _run(args: argparse.Namespace) -> int:
    cfg = _config()
    token = cfg.access_token.strip()
    if not token:
        print(
            "ERROR: no protocols.io access token configured. Set "
            "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN "
            "in backend/.env and retry.",
            file=sys.stderr,
        )
        return 1
    timeout = cfg.request_timeout_seconds

    if args.url:
        url = args.url
    else:
        print(f"[search] query={args.query!r} …")
        result = await protocols_io.search_protocols_io(
            args.query, access_token=token, limit=5, timeout=timeout
        )
        print(f"[search] {result.total} hit(s)")
        for hit in result.hits:
            print(f"  - {hit.title}\n    {hit.url}")
        if not result.hits:
            print("[search] no hits — nothing to fetch. Try another --query.")
            return 0
        url = result.hits[0].url

    print(f"\n[fetch] {url}")
    if args.raw:
        await _dump_raw_detail(url, token, timeout)

    payload = await protocols_io.fetch_protocols_io(
        url, access_token=token, timeout=timeout
    )
    if payload.error:
        print(f"[fetch] ERROR: {payload.error}", file=sys.stderr)
        return 1

    verdict = classify_license(payload.license)
    print(f"[fetch] title:           {payload.title}")
    print(f"[fetch] license raw:     {payload.license!r}")
    print(
        f"[fetch] license verdict: {verdict.normalized} "
        f"(import_allowed={verdict.import_allowed})"
    )
    print(f"[fetch] import_allowed:  {payload.import_allowed}")
    print(f"[fetch] license_note:    {payload.license_note}")
    print(f"[fetch] materials:       {len(payload.materials)}")
    print(f"[fetch] steps:           {len(payload.steps)}")
    print(f"[fetch] summary:         {payload.summary[:200]}")
    print("\n[ok] live protocols.io connector round-trip succeeded.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="F-0090 protocols.io live smoke test")
    parser.add_argument("--query", default="miniprep", help="search query")
    parser.add_argument(
        "--url", default="", help="skip search; fetch this protocol URL directly"
    )
    parser.add_argument(
        "--raw", action="store_true", help="also dump the raw v4 detail JSON"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
