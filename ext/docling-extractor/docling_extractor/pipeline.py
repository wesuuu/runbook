"""Wraps docling's DocumentConverter with the Batchrite extraction pipeline.

Pure function: takes a file path, returns an ExtractionResult. No I/O
beyond what docling does internally (model cache + OCR).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, List

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (AcceleratorDevice,
                                                AcceleratorOptions,
                                                EasyOcrOptions,
                                                PdfPipelineOptions)
from docling.document_converter import DocumentConverter, PdfFormatOption

from .image_externalizer import ExtractedPicture

logger = logging.getLogger(__name__)

# Docling occasionally classifies degenerate sub-50px regions (page
# background samples, sub-glyph crops, decorative rules) as "pictures".
# Stretched into a column they render as massive blurry artifacts. We
# reject anything whose larger dimension is below this threshold.
_MIN_PICTURE_MAX_DIMENSION = 48


@dataclass
class ExtractionResult:
    markdown: str
    page_count: int
    pictures: List[ExtractedPicture] = field(default_factory=list)
    flags: List[dict[str, Any]] = field(default_factory=list)


def build_converter(num_threads: int) -> DocumentConverter:
    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = True
    pdf_options.generate_picture_images = True
    pdf_options.ocr_options = EasyOcrOptions(
        lang=["en"],
        force_full_page_ocr=False,
    )
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=num_threads,
        device=AcceleratorDevice.AUTO,
    )

    # IMAGE pipeline: OCR off. The EasyOCR model cache is not guaranteed
    # to be present on the docling subprocess host, and a missing cache
    # surfaces as the bare "[Errno 2] No such file or directory" the
    # user sees on image uploads. Layout-only extraction always works;
    # gate OCR-on-images on a flag if a customer ever needs it.
    image_options = PdfPipelineOptions()
    image_options.do_ocr = False
    image_options.generate_picture_images = True
    image_options.accelerator_options = AcceleratorOptions(
        num_threads=num_threads,
        device=AcceleratorDevice.AUTO,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            InputFormat.IMAGE: PdfFormatOption(pipeline_options=image_options),
        }
    )


def _picture_too_small(pil_image: Any, png_bytes: bytes) -> bool:
    """Decide whether to drop a docling-detected picture as degenerate.

    We prefer the PIL image's ``size`` (no decode cost) and fall back to
    decoding the PNG bytes only if needed. Any failure returns False so
    we never drop a picture we can't measure.
    """
    width = height = 0
    size = getattr(pil_image, "size", None) if pil_image is not None else None
    if size and len(size) == 2:
        width, height = size
    elif png_bytes:
        try:
            from PIL import Image  # type: ignore

            with Image.open(BytesIO(png_bytes)) as probe:
                width, height = probe.size
        except Exception:  # noqa: BLE001
            return False
    if width <= 0 or height <= 0:
        return False
    return max(width, height) < _MIN_PICTURE_MAX_DIMENSION


def _iter_pictures(doc: Any) -> List[ExtractedPicture]:
    pictures: List[ExtractedPicture] = []
    for idx, item in enumerate(getattr(doc, "pictures", []) or []):
        image = getattr(item, "image", None)
        if image is None:
            continue
        pil_image = getattr(image, "pil_image", None)
        png = getattr(image, "to_bytes", None)
        if callable(png):
            data = png()
        else:
            if pil_image is None:
                continue
            buf = BytesIO()
            pil_image.save(buf, format="PNG")
            data = buf.getvalue()

        caption = ""
        captions = getattr(item, "captions", None)
        if captions:
            first = captions[0]
            caption = getattr(first, "text", "") or str(first)

        skip = _picture_too_small(pil_image, data)
        if skip:
            logger.debug(
                "Dropping degenerate docling picture #%d (max-dim < %dpx)",
                idx, _MIN_PICTURE_MAX_DIMENSION,
            )

        pictures.append(
            ExtractedPicture(
                index=idx, png_bytes=data, caption=caption, skip=skip
            )
        )
    return pictures


def _collect_flags(_doc: Any) -> List[dict[str, Any]]:
    """Phase 1: return an empty list. Confidence-derived flags are a follow-up."""
    return []


def run_pipeline(file_path: Path, num_threads: int) -> ExtractionResult:
    converter = build_converter(num_threads)
    logger.info("Running docling on %s", file_path)
    try:
        convert_result = converter.convert(str(file_path))
    except FileNotFoundError as e:
        # Surface the missing path in the message so future failures
        # self-diagnose instead of returning a bare "[Errno 2]".
        missing = getattr(e, "filename", None) or "unknown path"
        raise FileNotFoundError(
            f"docling could not open required file: {missing}"
        ) from e
    doc = convert_result.document

    markdown = doc.export_to_markdown()
    page_count = (
        doc.num_pages()
        if callable(getattr(doc, "num_pages", None))
        else 0
    )
    pictures = _iter_pictures(doc)
    flags = _collect_flags(doc)

    return ExtractionResult(
        markdown=markdown,
        page_count=page_count,
        pictures=pictures,
        flags=flags,
    )
