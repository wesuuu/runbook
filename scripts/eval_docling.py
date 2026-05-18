"""Evaluate docling document conversion across configuration variants.

For each input file x variant, runs DocumentConverter().convert(), times it,
and writes <basename>.<variant>.{md,html,json} to the output directory plus a
one-line summary to stdout.

Used to validate whether docling is suitable for the library extraction
pipeline (TD-0085).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from docling.datamodel.accelerator_options import (
    AcceleratorDevice,
    AcceleratorOptions,
)
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode

VARIANTS = ("default", "no-ocr", "cpu", "with-images")


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def cache_dir_bytes() -> int:
    """Total bytes used by docling-related model caches.

    docling 2.x splits its caches across multiple locations:
    - HuggingFace hub (layout, tableformer, doc-converter weights)
    - rapidocr ONNX models inside the active venv
    """
    hf_hub = Path.home() / ".cache" / "huggingface" / "hub"
    total = 0
    if hf_hub.exists():
        for entry in hf_hub.iterdir():
            name = entry.name.lower()
            if entry.is_dir() and (
                "docling" in name or "tableformer" in name
            ):
                total += _dir_bytes(entry)

    venv_root = Path(sys.prefix)
    for rapidocr_models in venv_root.rglob("rapidocr/models"):
        total += _dir_bytes(rapidocr_models)

    return total


def format_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


def build_converter(variant: str) -> DocumentConverter:
    """Construct a DocumentConverter wired for the given variant.

    - default:     AUTO accelerator, OCR on (baseline)
    - no-ocr:      AUTO accelerator, OCR off (text-native PDFs)
    - cpu:         forced CPU, OCR on (worst-case for no-GPU containers)
    - with-images: default + generate_picture_images=True (extracts figure
      bitmaps so export_to_html(ImageRefMode.EMBEDDED) embeds them as base64)
    """
    generate_picture_images = False
    if variant == "default":
        device = AcceleratorDevice.AUTO
        do_ocr = True
    elif variant == "no-ocr":
        device = AcceleratorDevice.AUTO
        do_ocr = False
    elif variant == "cpu":
        device = AcceleratorDevice.CPU
        do_ocr = True
    elif variant == "with-images":
        device = AcceleratorDevice.AUTO
        do_ocr = True
        generate_picture_images = True
    else:
        raise ValueError(f"unknown variant: {variant}")

    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = do_ocr
    pdf_options.generate_picture_images = generate_picture_images
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=4, device=device
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
        }
    )


@dataclass
class RunResult:
    input: Path
    variant: str
    seconds: float
    pages: int
    md_chars: int
    html_chars: int
    device: str


def run_one(input_path: Path, variant: str, out_dir: Path) -> RunResult:
    """Convert one (input, variant) pair and write outputs.

    Raises on conversion failure so a bad run can't be silently confused
    with a good one.
    """
    converter = build_converter(variant)

    start = time.perf_counter()
    result = converter.convert(str(input_path))
    elapsed = time.perf_counter() - start

    doc = result.document
    md = doc.export_to_markdown()
    html = doc.export_to_html(image_mode=ImageRefMode.EMBEDDED)
    js = doc.export_to_dict()

    basename = input_path.stem
    (out_dir / f"{basename}.{variant}.md").write_text(md, encoding="utf-8")
    (out_dir / f"{basename}.{variant}.html").write_text(html, encoding="utf-8")
    (out_dir / f"{basename}.{variant}.json").write_text(
        json.dumps(js, indent=2, default=str), encoding="utf-8"
    )

    pages = len(doc.pages) if hasattr(doc, "pages") and doc.pages else 0
    pdf_opts = converter.format_to_options[InputFormat.PDF].pipeline_options
    device = str(pdf_opts.accelerator_options.device)

    return RunResult(
        input=input_path,
        variant=variant,
        seconds=elapsed,
        pages=pages,
        md_chars=len(md),
        html_chars=len(html),
        device=device,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        type=Path,
        help="Input file path. Repeatable.",
    )
    parser.add_argument(
        "--variant",
        action="append",
        choices=VARIANTS,
        help=(
            f"Variant to run. Repeatable. Defaults to all: "
            f"{', '.join(VARIANTS)}"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("scripts/mocks/out"),
        help="Directory to write generated outputs.",
    )
    args = parser.parse_args(argv)

    variants = args.variant or list(VARIANTS)

    for input_path in args.input:
        if not input_path.exists():
            print(f"ERROR: input not found: {input_path}", file=sys.stderr)
            return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)

    cache_before = cache_dir_bytes()
    print(f"cache_before={format_bytes(cache_before)}")
    print(
        f"inputs={len(args.input)} variants={variants} "
        f"out_dir={args.out_dir}"
    )

    results: list[RunResult] = []
    for input_path in args.input:
        for variant in variants:
            print(f"-> {input_path.name} [{variant}] ...", flush=True)
            result = run_one(input_path, variant, args.out_dir)
            results.append(result)
            per_page = (
                result.seconds / result.pages if result.pages else 0.0
            )
            print(
                f"   {result.variant:8s} pages={result.pages:4d} "
                f"seconds={result.seconds:7.1f} sec/page={per_page:5.2f} "
                f"md_chars={result.md_chars:7d} "
                f"html_chars={result.html_chars:9d} "
                f"device={result.device}",
                flush=True,
            )

    cache_after = cache_dir_bytes()
    delta = cache_after - cache_before
    print(
        f"cache_after={format_bytes(cache_after)} "
        f"delta={format_bytes(delta)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
