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

    # Resolve via the ``extract`` module so tests can patch
    # ``extract.DocumentConverter`` and intercept construction.
    import extract  # local import avoids circular import at module load

    return extract.DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
        }
    )


def _iter_pictures(doc: Any) -> List[ExtractedPicture]:
    pictures: List[ExtractedPicture] = []
    for idx, item in enumerate(getattr(doc, "pictures", []) or []):
        image = getattr(item, "image", None)
        if image is None:
            continue
        png = getattr(image, "to_bytes", None)
        if callable(png):
            data = png()
        else:
            pil_image = getattr(image, "pil_image", None)
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

        pictures.append(
            ExtractedPicture(index=idx, png_bytes=data, caption=caption)
        )
    return pictures


def _collect_flags(_doc: Any) -> List[dict[str, Any]]:
    """Phase 1: return an empty list. Confidence-derived flags are a follow-up."""
    return []


def run_pipeline(file_path: Path, num_threads: int) -> ExtractionResult:
    converter = build_converter(num_threads)
    logger.info("Running docling on %s", file_path)
    convert_result = converter.convert(str(file_path))
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
