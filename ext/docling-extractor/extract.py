"""CLI entrypoint for the standalone docling extractor.

Usage:
    python extract.py --input <file> --output-dir <dir> [--num-threads N]

Writes <output-dir>/refined.md, <output-dir>/images/{N}.png, and
<output-dir>/result.json. Exit code 0 on success, non-zero on failure
(error message on stderr).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

from docling_extractor.heartbeat import HeartbeatPoster
from docling_extractor.image_externalizer import (externalize_images,
                                                  rewrite_markdown_image_refs)
from docling_extractor.pipeline import run_pipeline

logger = logging.getLogger("docling_extractor")


_EXT_TO_SOURCE_FORMAT = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".png": "IMAGE",
    ".jpg": "IMAGE",
    ".jpeg": "IMAGE",
    ".tif": "IMAGE",
    ".tiff": "IMAGE",
    ".webp": "IMAGE",
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batchrite docling extractor")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--num-threads", type=int, default=4)
    # heartbeat (all three required together; all-optional means "no heartbeat")
    p.add_argument("--heartbeat-url", type=str, default=None)
    p.add_argument("--heartbeat-token", type=str, default=None)
    p.add_argument("--heartbeat-interval-seconds", type=float, default=10.0)
    return p.parse_args(argv)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 2

    poster: HeartbeatPoster | None = None
    if args.heartbeat_url and args.heartbeat_token:
        poster = HeartbeatPoster(
            url=args.heartbeat_url,
            token=args.heartbeat_token,
            interval_seconds=args.heartbeat_interval_seconds,
        )
        poster.start()

    try:
        try:
            result = run_pipeline(args.input, num_threads=args.num_threads)
        except Exception as exc:  # noqa: BLE001
            print(f"extraction failed: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return 1

        args.output_dir.mkdir(parents=True, exist_ok=True)
        images_dir = args.output_dir / "images"
        externalize_images(result.pictures, images_dir)
        refined_md = rewrite_markdown_image_refs(result.markdown, result.pictures)
        (args.output_dir / "refined.md").write_text(refined_md)

        source_format = _EXT_TO_SOURCE_FORMAT.get(
            args.input.suffix.lower(), "PDF"
        )
        payload = {
            "page_count": result.page_count,
            "image_count": sum(1 for p in result.pictures if not p.skip),
            "flags": result.flags,
            "ocr_engine": "easyocr",
            "source_format": source_format,
        }
        (args.output_dir / "result.json").write_text(json.dumps(payload, indent=2))
        return 0
    finally:
        if poster is not None:
            poster.stop()


if __name__ == "__main__":
    sys.exit(main())
