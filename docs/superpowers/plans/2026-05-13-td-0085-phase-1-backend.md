# TD-0085 Phase 1 — Backend Docling Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the vision-LLM extraction pipeline with docling for PDF/DOCX/image uploads. Move docling into a **standalone Python project at `ext/docling-extractor/`** with its own `.venv` (zero backend deps; zero docling deps in the backend). Add storage for refined markdown + externalized images, register a `document_refinement` AI capability, expose refinement endpoints, and dispatch extraction through a new **generic** `BackgroundHandler` abstraction in `services/core/` (`local` for now, `cloud-gpu` stubbed) that other GPU/heavy workloads can register with later.

**Architecture:** Upload → store file → enqueue job via `BackgroundHandler.launch("document_extract", document_id=...)` → the `document_extract` job shells out to `ext/docling-extractor/extract.py` via `asyncio.create_subprocess_exec` → the script writes `refined.md` + `images/N.png` + `result.json` into a per-document output dir → the job reads those artifacts and persists to DB → endpoints serve markdown, images, source-page thumbnails, AI refinement, and a "mark complete" action that triggers the existing chunker/embedder against the **refined** markdown. Jobs register themselves with a module-level `JOB_REGISTRY` via `@register_job(name)`; the handler dispatches by name so a cloud-gpu backend can run the same script on a remote GPU instance later. The old `process_document` / `enrich_document` / `build_book` chain and `document_structure.py` are deleted along with the `doc_structure` capability.

**Tech Stack:** FastAPI (async) · SQLAlchemy 2.0 · Alembic · Poetry (backend; **docling is NOT a backend dep**) · standalone `ext/docling-extractor/` Poetry project with `docling 2.93+` · pymupdf (backend, source-page rendering only) · pydantic-ai 1.75+ · pytest with httpx.AsyncClient · pgvector (existing) · `BackgroundJob` rows for progress.

---

## File map

Files **created** in Phase 1:

| Path | Responsibility |
| --- | --- |
| `ext/docling-extractor/pyproject.toml` | Standalone Poetry project. Owns `docling = "^2.93"` + `pillow` (for image saving). Backend never imports from here. |
| `ext/docling-extractor/README.md` | One-page doc: how to install (`poetry install`), how to invoke (`python extract.py --input X --output-dir Y`), and the output contract (refined.md / images/ / result.json). |
| `ext/docling-extractor/docling_extractor/__init__.py` | Package marker. |
| `ext/docling-extractor/docling_extractor/pipeline.py` | Wraps `DocumentConverter` with the hardcoded Batchrite pipeline (EasyOCR English, AUTO accelerator, picture images on). Pure function: file path → in-memory `ExtractionResult`. |
| `ext/docling-extractor/docling_extractor/image_externalizer.py` | Writes PNG bytes from docling's picture iterator to `{output_dir}/images/{n}.png`. Rewrites `<!-- image -->` placeholders in the markdown to `![<caption>](images/{n}.png)`. |
| `ext/docling-extractor/extract.py` | CLI entrypoint. Parses `--input`, `--output-dir`, `--num-threads`. Runs the pipeline, writes `refined.md`, `images/N.png`, `result.json` into `--output-dir`. Exit code 0 on success, non-zero on failure (stderr carries the error message). |
| `ext/docling-extractor/tests/test_extract_cli.py` | Unit tests for the CLI (mocking `DocumentConverter` from inside the ext project). |
| `ext/docling-extractor/tests/test_image_externalizer.py` | Unit tests for image externalization (lives in ext, not backend). |
| `backend/app/services/core/background_handler.py` | Generic `BackgroundHandler` ABC + `LocalBackgroundHandler` + `CloudGpuBackgroundHandler` stub + `JOB_REGISTRY` + `register_job` decorator + `get_background_handler()` factory. Lives in `core/` (next to `task_runner.py`) so any future heavy/GPU job can register with it. |
| `backend/app/services/documents/extraction/__init__.py` | Package marker. |
| `backend/app/services/documents/extraction/extract_job.py` | The coroutine dispatched by the handler. Registers itself as `"document_extract"` via `@register_job`. Owns the DB session, `BackgroundJob` lifecycle, status transitions, **spawns `ext/docling-extractor/extract.py` via `asyncio.create_subprocess_exec`**, reads the result artifacts, persists `stored_markdown`/`images_dir`/`refinement_flags`. |
| `backend/app/services/documents/extraction/source_page.py` | Renders a single PDF page to PNG via pymupdf (for the editor's left-rail thumbnail). Pure function. Backend-only — pymupdf is already a runtime dep. |
| `backend/app/services/documents/refinement/__init__.py` | Package marker. |
| `backend/app/services/documents/refinement/refinement_service.py` | Module functions: `save_markdown`, `mark_in_progress`, `mark_complete_and_index`, `reopen_refinement`. No class state. |
| `backend/app/services/documents/refinement/ai_fix.py` | `apply_ai_fix(db, document_id, payload)` — resolves `document_refinement` model, builds the prompt, returns suggested markdown. Domain logic for the AI endpoint. |
| `backend/app/services/documents/markdown_assets.py` | Helpers shared by endpoints: resolve absolute image path, rewrite relative-image markdown for read API, MIME-type → `DocumentSourceFormat` mapping. |
| `backend/alembic/versions/f0041_docling_document_columns.py` | Migration: add `source_format`, `stored_markdown`, `images_dir`, `refinement_status`, `refinement_flags`, `ocr_engine`, `refined_by_id`, `refined_at` columns; add `EXTRACTING`/`AWAITING_REFINEMENT`/`INDEXING` to the `DocumentStatus` allow-list (column is a `String`, no DB enum to alter). |
| `backend/tests/unit/test_background_handler.py` | Unit tests for `get_background_handler()` factory, `JOB_REGISTRY` dispatch, and stub raising `NotImplementedError`. |
| `backend/tests/unit/test_extract_job.py` | Unit tests for the job: subprocess invocation contract, artifact parsing, status transitions. The subprocess is mocked (no docling required in backend tests). |
| `backend/tests/unit/test_refinement_service.py` | Unit tests for refinement state transitions. |
| `backend/tests/integration/test_library_docling.py` | Integration tests for upload→extract happy path and the new endpoints. |

Files **modified** in Phase 1:

| Path | Change |
| --- | --- |
| `backend/pyproject.toml` | **No docling dependency.** Just ensures `pymupdf` stays in `[tool.poetry.dependencies]` (it already does). |
| `backend/app/core/config.py` | Remove `ai_doc_structure_provider`/`ai_doc_structure_model`. Add `ai_document_refinement_provider`/`_model`, `background_handler`, `docling_script_python`, `docling_script_path`, `docling_num_threads` (passed through to the script). |
| `backend/app/models/ai.py` | Remove `"doc_structure"` from `SUPPORTED_CAPABILITIES` + `DEFAULT_CONFIGS`. Add `"document_refinement"` (default: `anthropic` / `claude-sonnet-4-5-20250929`). |
| `backend/app/models/library.py` | Add `DocumentSourceFormat`, `RefinementStatus` enums; extend `DocumentStatus` with `EXTRACTING`/`AWAITING_REFINEMENT`/`INDEXING`; add the eight new columns. Refresh `ALLOWED_DOCUMENT_TYPES` to the Phase 1 allowlist. |
| `backend/app/schemas/library.py` | New schemas: `RefineAiRequest`, `RefineAiResponse`, `RefineCompleteRequest`, `MarkdownPayload`, `RefinementFlag`. Extend `DocumentResponse`/`DocumentDetailResponse` to expose new fields. |
| `backend/app/api/endpoints/library.py` | Swap `build_book` submission for `get_background_handler().launch("document_extract", document_id=doc.id)`; replace `enrich_document_endpoint` with the new refinement routes; reject `source_url` on `POST /documents`. |
| `backend/app/services/ai/ai_config.py` | No code changes needed beyond capability list (handled via `models/ai.py`). |
| `backend/app/services/documents/markdown_chunker.py` | Delete `rechunk_with_structure` and any structure-aware helpers that consumed `doc_structure` output. Keep `chunk_markdown` (the path the new `mark_complete_and_index` will call). |
| `backend/app/services/documents/document_processor.py` | Delete `process_document`, `enrich_document`, `build_book` (and any helpers exclusive to them: `_extract_pdf_page_range`, `_get_pdf_page_count` if unused, etc.). Keep only what `mark_complete_and_index` will reuse (embedding loop, `_pad_embedding`); move it into `services/documents/refinement/indexing.py` if cleaner. |
| `backend/app/services/documents/document_structure.py` | **Deleted** outright. |

Out of scope (Phase 2 / Phase C): all `frontend/`, `CloudGpuBackgroundHandler` actually doing dispatch, and `.claude/rules` updates beyond what already exists.

---

## Sequencing

The plan is ordered so that each task ends with a green test suite and a commit. Tasks 1–2 build the standalone `ext/docling-extractor/` project (scaffold + CLI). Tasks 3–6 lay backend foundation (settings, AI capability, model, migration). Task 7 wires up the generic BackgroundHandler and the subprocess-based `document_extract` job. **Task 8 adds the heartbeat + watchdog plumbing** so a hung extractor surfaces as a failure instead of an indefinite "EXTRACTING" status. Task 9 adds the pymupdf source-page renderer. Tasks 10–12 add refinement service + AI fix + indexing trigger. Task 13 wires the endpoints. Task 14 deletes legacy code. Task 15 is the integration smoke test.

---

### Task 1: Scaffold the standalone `ext/docling-extractor/` project

**Files:**
- Create: `ext/docling-extractor/pyproject.toml`
- Create: `ext/docling-extractor/README.md`
- Create: `ext/docling-extractor/docling_extractor/__init__.py` (empty)
- Create: `ext/docling-extractor/tests/__init__.py` (empty)
- Create: `ext/docling-extractor/.gitignore`

- [ ] **Step 1: Confirm `ext/` does not already exist**

Run: `ls ext/ 2>/dev/null && echo EXISTS || echo MISSING`
Expected: `MISSING`. If `EXISTS`, stop and inspect — another feature may have introduced it.

- [ ] **Step 2: Create the directory layout**

```bash
mkdir -p ext/docling-extractor/docling_extractor
mkdir -p ext/docling-extractor/tests
```

- [ ] **Step 3: Write `pyproject.toml`**

Create `ext/docling-extractor/pyproject.toml`:

```toml
[tool.poetry]
name = "batchrite-docling-extractor"
version = "0.1.0"
description = "Standalone docling-based document extractor for Batchrite (TD-0085). Invoked as a subprocess by the backend; ships with its own venv so docling/torch stay out of the backend image."
authors = ["Batchrite"]
package-mode = false

[tool.poetry.dependencies]
python = "^3.11"
docling = "^2.93"
pillow = "^10.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```

`package-mode = false` is important: this is an application, not a library. Poetry won't try to build a wheel.

- [ ] **Step 4: Write `.gitignore`**

Create `ext/docling-extractor/.gitignore`:

```
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 5: Write `README.md`**

Create `ext/docling-extractor/README.md`:

````markdown
# docling-extractor

Standalone document-extraction service for Batchrite. Lives outside `backend/` so its (heavy) deps — docling, torch, easyocr — never touch the backend image or venv. Invoked as a subprocess by `backend/app/services/documents/extraction/extract_job.py`.

## Install

```bash
cd ext/docling-extractor
poetry install
```

## Run

```bash
poetry run python extract.py --input /path/to/file.pdf --output-dir /tmp/out --num-threads 4
```

## Output contract

The script writes the following into `--output-dir`:

- `refined.md` — markdown with image refs already rewritten to `images/N.png`
- `images/N.png` — one PNG per externalized picture (N is the picture index)
- `result.json` — `{ "page_count": int, "image_count": int, "flags": [...], "ocr_engine": "easyocr", "source_format": "PDF" | "DOCX" | "IMAGE" }`

Exit code 0 on success; non-zero on failure with the error message on stderr.

## Production deployment

In Phase 1 this runs locally via subprocess (selected by the backend setting `background_handler=local`). When we move to a dedicated GPU machine (Phase C), `background_handler=cloud-gpu` will run the same script on a remote instance with the same CLI and output contract.
````

- [ ] **Step 6: Add package markers**

Create empty files:

```bash
: > ext/docling-extractor/docling_extractor/__init__.py
: > ext/docling-extractor/tests/__init__.py
```

- [ ] **Step 7: Install the project**

```bash
cd ext/docling-extractor && poetry install
```

Expected: docling, torch, easyocr, pillow install into `ext/docling-extractor/.venv/`. This takes several minutes the first time.

- [ ] **Step 8: Verify the venv works**

```bash
ext/docling-extractor/.venv/bin/python -c "from docling.document_converter import DocumentConverter; print('ok')"
```

Expected: `ok` printed. The path `ext/docling-extractor/.venv/bin/python` is what the backend will invoke later — capture it now so you know it works.

- [ ] **Step 9: Commit**

```bash
git add ext/docling-extractor/pyproject.toml \
        ext/docling-extractor/poetry.lock \
        ext/docling-extractor/README.md \
        ext/docling-extractor/.gitignore \
        ext/docling-extractor/docling_extractor/__init__.py \
        ext/docling-extractor/tests/__init__.py
git commit -m "feat(ext): scaffold standalone docling-extractor project (TD-0085)"
```

---

### Task 2: Implement `ext/docling-extractor/extract.py` CLI

**Files:**
- Create: `ext/docling-extractor/docling_extractor/pipeline.py`
- Create: `ext/docling-extractor/docling_extractor/image_externalizer.py`
- Create: `ext/docling-extractor/extract.py`
- Test: `ext/docling-extractor/tests/test_extract_cli.py`
- Test: `ext/docling-extractor/tests/test_image_externalizer.py`

All commands in this task run from `ext/docling-extractor/` with that project's venv active (or via `poetry run`).

- [ ] **Step 1: Write the failing image-externalizer test**

Create `ext/docling-extractor/tests/test_image_externalizer.py`:

```python
from pathlib import Path

from docling_extractor.image_externalizer import (ExtractedPicture,
                                                  externalize_images,
                                                  rewrite_markdown_image_refs)

# Minimal 1x1 transparent PNG
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "89000000017352474200aece1ce90000000d49444154789c63"
    "f8cf00000000ffff03000001ff01ff5f5f5f5e0000000049454e44ae426082"
)


def test_writes_pngs_to_disk(tmp_path: Path):
    pics = [
        ExtractedPicture(index=0, png_bytes=PNG_1X1, caption="Fig 1"),
        ExtractedPicture(index=1, png_bytes=PNG_1X1, caption=""),
    ]
    externalize_images(pics, tmp_path)
    assert (tmp_path / "0.png").read_bytes() == PNG_1X1
    assert (tmp_path / "1.png").read_bytes() == PNG_1X1


def test_rewrites_placeholders_in_order():
    pics = [
        ExtractedPicture(index=0, png_bytes=PNG_1X1, caption="Fig 1"),
        ExtractedPicture(index=1, png_bytes=PNG_1X1, caption=""),
    ]
    md_in = "Para 1\n\n<!-- image -->\n\nPara 2\n\n<!-- image -->\n\nPara 3"
    md_out = rewrite_markdown_image_refs(md_in, pics)
    assert "![Fig 1](images/0.png)" in md_out
    assert "![](images/1.png)" in md_out
    assert "<!-- image -->" not in md_out
```

- [ ] **Step 2: Run and confirm failure**

```bash
poetry run pytest tests/test_image_externalizer.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the image externalizer**

Create `ext/docling-extractor/docling_extractor/image_externalizer.py`:

```python
"""Externalize docling picture regions to PNG files on disk.

Docling's ``export_to_markdown()`` inserts literal ``<!-- image -->``
placeholders where a figure would render. We replace each placeholder
in order with ``![caption](images/N.png)`` after writing the PNG bytes
to ``{output_dir}/images/{N}.png``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

_PLACEHOLDER = "<!-- image -->"
_PLACEHOLDER_RE = re.compile(re.escape(_PLACEHOLDER))


@dataclass
class ExtractedPicture:
    index: int
    png_bytes: bytes
    caption: str = ""


def externalize_images(
    pictures: List[ExtractedPicture], images_dir: Path
) -> None:
    images_dir.mkdir(parents=True, exist_ok=True)
    for pic in pictures:
        (images_dir / f"{pic.index}.png").write_bytes(pic.png_bytes)


def rewrite_markdown_image_refs(
    markdown: str, pictures: List[ExtractedPicture]
) -> str:
    iterator = iter(pictures)

    def _sub(_match: re.Match) -> str:
        try:
            pic = next(iterator)
        except StopIteration:
            return ""
        caption = pic.caption or ""
        return f"![{caption}](images/{pic.index}.png)"

    return _PLACEHOLDER_RE.sub(_sub, markdown)
```

- [ ] **Step 4: Run and confirm pass**

```bash
poetry run pytest tests/test_image_externalizer.py -v
```
Expected: both PASS.

- [ ] **Step 5: Write the failing CLI test**

Create `ext/docling-extractor/tests/test_extract_cli.py`:

```python
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _fake_docling_doc(markdown: str, page_count: int):
    doc = MagicMock()
    doc.export_to_markdown.return_value = markdown
    doc.num_pages.return_value = page_count
    doc.pictures = []
    return doc


def _run_cli(input_path: Path, output_dir: Path, num_threads: int = 4):
    """Invoke extract.main() with patched docling for deterministic tests."""
    import extract

    convert_result = MagicMock()
    convert_result.document = _fake_docling_doc("# Title\n\nBody.", 3)

    with patch.object(extract, "DocumentConverter") as ConverterCls:
        ConverterCls.return_value.convert.return_value = convert_result
        argv = [
            "extract.py",
            "--input", str(input_path),
            "--output-dir", str(output_dir),
            "--num-threads", str(num_threads),
        ]
        with patch.object(sys, "argv", argv):
            return extract.main()


def test_cli_writes_artifacts(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"

    exit_code = _run_cli(pdf, out)
    assert exit_code == 0

    refined = (out / "refined.md").read_text()
    assert refined == "# Title\n\nBody."
    result = json.loads((out / "result.json").read_text())
    assert result["page_count"] == 3
    assert result["image_count"] == 0
    assert result["ocr_engine"] == "easyocr"
    assert result["source_format"] == "PDF"


def test_cli_creates_output_dir_if_missing(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "deeper" / "out"

    exit_code = _run_cli(pdf, out)
    assert exit_code == 0
    assert (out / "refined.md").exists()


def test_cli_missing_input_returns_nonzero(tmp_path: Path):
    out = tmp_path / "out"
    import extract
    argv = ["extract.py", "--input", str(tmp_path / "missing.pdf"),
            "--output-dir", str(out)]
    with patch.object(sys, "argv", argv):
        exit_code = extract.main()
    assert exit_code != 0
```

> Note: the test imports `extract` as a top-level module. `extract.py` is invoked directly (not as a package member), and tests run from `ext/docling-extractor/` — pytest's default rootdir behavior picks it up. If pytest can't find it, add `pythonpath = ["."]` to `[tool.pytest.ini_options]` in `pyproject.toml`.

- [ ] **Step 6: Run and confirm failure**

```bash
poetry run pytest tests/test_extract_cli.py -v
```
Expected: ImportError on `extract`.

- [ ] **Step 7: Implement the pipeline module**

Create `ext/docling-extractor/docling_extractor/pipeline.py`:

```python
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

    return DocumentConverter(
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
```

- [ ] **Step 8: Implement the CLI**

Create `ext/docling-extractor/extract.py`:

```python
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

# Re-exported so tests can patch `extract.DocumentConverter`.
from docling.document_converter import DocumentConverter  # noqa: F401

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
    return p.parse_args(argv)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 2

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
        "image_count": len(result.pictures),
        "flags": result.flags,
        "ocr_engine": "easyocr",
        "source_format": source_format,
    }
    (args.output_dir / "result.json").write_text(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9: Run all ext tests**

```bash
cd ext/docling-extractor && poetry run pytest -v
```
Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add ext/docling-extractor/extract.py \
        ext/docling-extractor/docling_extractor/pipeline.py \
        ext/docling-extractor/docling_extractor/image_externalizer.py \
        ext/docling-extractor/tests/test_extract_cli.py \
        ext/docling-extractor/tests/test_image_externalizer.py
git commit -m "feat(ext): docling extractor CLI + pipeline + image externalizer"
```

---

### Task 3: Settings — add docling + background_handler knobs, remove doc_structure

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/unit/test_config.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_config.py` (or append if exists):

```python
from app.core.config import Settings


def test_background_handler_and_docling_settings_have_sensible_defaults():
    s = Settings()
    assert s.background_handler == "local"
    assert s.docling_num_threads == 4
    # Default paths point at the ext/ project relative to the repo root.
    assert s.docling_script_python.endswith(
        "ext/docling-extractor/.venv/bin/python"
    )
    assert s.docling_script_path.endswith(
        "ext/docling-extractor/extract.py"
    )


def test_document_refinement_capability_env_fields_exist():
    s = Settings()
    assert s.ai_document_refinement_provider == ""
    assert s.ai_document_refinement_model == ""


def test_doc_structure_capability_fields_removed():
    s = Settings()
    assert not hasattr(s, "ai_doc_structure_provider")
    assert not hasattr(s, "ai_doc_structure_model")
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `cd backend && pytest tests/unit/test_config.py -v`
Expected: `test_doc_structure_capability_fields_removed` PASSES (already absent? no — it currently FAILS because fields exist). The other two FAIL with `AttributeError`.

- [ ] **Step 3: Update `config.py`**

In `backend/app/core/config.py`:
- **Remove** lines `ai_doc_structure_provider: str = ""` and `ai_doc_structure_model: str = ""`.
- **Add** under the "AI env var fallbacks" block:

```python
    ai_document_refinement_provider: str = ""
    ai_document_refinement_model: str = ""
```

- **Add** a new block (near the existing `task_runner_backend` setting):

```python
    # Background-job dispatch (TD-0085).
    # "local" runs jobs in-process via the TaskRunner;
    # "cloud-gpu" will dispatch to a dedicated GPU service.
    background_handler: str = "local"  # "local" | "cloud-gpu"

    # Docling extractor (TD-0085) — paths to the standalone ext/ project's
    # interpreter and CLI entrypoint. Defaults assume the repo layout
    # (backend/ and ext/ are siblings); override via env vars in deploy.
    docling_script_python: str = str(
        Path(__file__).resolve().parents[3]
        / "ext"
        / "docling-extractor"
        / ".venv"
        / "bin"
        / "python"
    )
    docling_script_path: str = str(
        Path(__file__).resolve().parents[3]
        / "ext"
        / "docling-extractor"
        / "extract.py"
    )
    docling_num_threads: int = 4
```

> The `Path(__file__).resolve().parents[3]` walks from `backend/app/core/config.py` up to the repo root. If `config.py` is at a different depth in the backend, adjust the `parents[N]` index — verify with `python -c "from pathlib import Path; print(Path('backend/app/core/config.py').resolve().parents[3])"` from the repo root before committing. `from pathlib import Path` may need to be added to `config.py`'s imports (it usually already is).

- [ ] **Step 4: Run tests to verify**

Run: `cd backend && pytest tests/unit/test_config.py -v`
Expected: all three PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/unit/test_config.py
git commit -m "feat(config): add background_handler + docling script paths; drop doc_structure capability env fields"
```

---

### Task 4: Capability registry — swap `doc_structure` for `document_refinement`

**Files:**
- Modify: `backend/app/models/ai.py`
- Test: `backend/tests/unit/test_ai_capabilities.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create or append `backend/tests/unit/test_ai_capabilities.py`:

```python
from app.models.ai import DEFAULT_CONFIGS, SUPPORTED_CAPABILITIES


def test_document_refinement_capability_registered():
    assert "document_refinement" in SUPPORTED_CAPABILITIES
    cfg = DEFAULT_CONFIGS["document_refinement"]
    assert cfg["provider"] == "anthropic"
    assert cfg["model_name"].startswith("claude-sonnet-4")


def test_doc_structure_capability_removed():
    assert "doc_structure" not in SUPPORTED_CAPABILITIES
    assert "doc_structure" not in DEFAULT_CONFIGS
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && pytest tests/unit/test_ai_capabilities.py -v`
Expected: both tests FAIL.

- [ ] **Step 3: Update `models/ai.py`**

In `backend/app/models/ai.py`:
- In `SUPPORTED_CAPABILITIES`, **delete** the `"doc_structure",` line. **Insert** `"document_refinement",` (alphabetical order: after `"chat_summary"`).
- In `DEFAULT_CONFIGS`, **delete** the `"doc_structure": {...}` entry. **Insert**:

```python
    "document_refinement": {
        "provider": "anthropic",
        "model_name": "claude-sonnet-4-5-20250929",
    },
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/test_ai_capabilities.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/ai.py backend/tests/unit/test_ai_capabilities.py
git commit -m "feat(ai): register document_refinement capability; remove doc_structure"
```

---

### Task 5: Model + enum changes for the `Document` row

**Files:**
- Modify: `backend/app/models/library.py`
- Test: `backend/tests/unit/test_document_model.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_document_model.py`:

```python
from app.models.library import (ALLOWED_DOCUMENT_TYPES, Document,
                                DocumentSourceFormat, DocumentStatus,
                                RefinementStatus)


def test_new_status_values_present():
    values = {s.value for s in DocumentStatus}
    assert "EXTRACTING" in values
    assert "AWAITING_REFINEMENT" in values
    assert "INDEXING" in values
    # Legacy values preserved for backwards compatibility
    assert "INDEXED" in values
    assert "ENRICHED" in values


def test_source_format_enum():
    assert DocumentSourceFormat.PDF.value == "PDF"
    assert DocumentSourceFormat.DOCX.value == "DOCX"
    assert DocumentSourceFormat.IMAGE.value == "IMAGE"


def test_refinement_status_enum():
    values = {s.value for s in RefinementStatus}
    assert values == {
        "NOT_REQUIRED", "PENDING", "IN_PROGRESS", "COMPLETE",
    }


def test_document_has_new_columns():
    cols = {c.name for c in Document.__table__.columns}
    for expected in [
        "source_format",
        "stored_markdown",
        "images_dir",
        "refinement_status",
        "refinement_flags",
        "ocr_engine",
        "refined_by_id",
        "refined_at",
    ]:
        assert expected in cols, f"missing column: {expected}"


def test_allowed_document_types_phase1():
    # Only PDF, DOCX, and image MIMEs. Text/markdown/html/rtf removed.
    assert "application/pdf" in ALLOWED_DOCUMENT_TYPES
    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in ALLOWED_DOCUMENT_TYPES
    )
    assert "image/png" in ALLOWED_DOCUMENT_TYPES
    assert "image/jpeg" in ALLOWED_DOCUMENT_TYPES
    assert "image/tiff" in ALLOWED_DOCUMENT_TYPES
    assert "image/webp" in ALLOWED_DOCUMENT_TYPES
    assert "text/plain" not in ALLOWED_DOCUMENT_TYPES
    assert "text/markdown" not in ALLOWED_DOCUMENT_TYPES
    assert "text/html" not in ALLOWED_DOCUMENT_TYPES
    assert "application/rtf" not in ALLOWED_DOCUMENT_TYPES
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && pytest tests/unit/test_document_model.py -v`
Expected: every test FAILS with `AttributeError` / missing values.

- [ ] **Step 3: Edit `models/library.py`**

In `backend/app/models/library.py`:

1. Replace the `ALLOWED_DOCUMENT_TYPES` set with:

```python
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
}
```

Also update `MIME_EXTENSION_MAP` to only contain entries for these MIMEs (drop txt/md/rtf/html/heic). Keep `MAGIC_BYTES` unchanged (PDF/PNG/JPEG signatures still apply).

2. Replace the `DocumentStatus` enum with:

```python
class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    AWAITING_REFINEMENT = "AWAITING_REFINEMENT"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"
    # Legacy values preserved (treated as READY by viewers)
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    ENRICHED = "ENRICHED"
```

3. Add two new enums above `Document`:

```python
class DocumentSourceFormat(str, enum.Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    IMAGE = "IMAGE"


class RefinementStatus(str, enum.Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
```

4. Inside the `Document` class, append after the existing `structure_metadata` column (before the `chunks` relationship):

```python
    source_format: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stored_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    images_dir: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    refinement_status: Mapped[str] = mapped_column(
        String,
        default=RefinementStatus.PENDING.value,
        server_default="NOT_REQUIRED",  # existing rows get NOT_REQUIRED
        nullable=False,
    )
    refinement_flags: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    ocr_engine: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    refined_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    refined_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

5. Update `VIEWABLE_STATUSES` to include `READY` only (existing constant); leave it alone if already covers the legacy values.

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/test_document_model.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/library.py backend/tests/unit/test_document_model.py
git commit -m "feat(models): add docling columns and refinement enums to Document"
```

---

### Task 6: Alembic migration for the new columns

**Files:**
- Create: `backend/alembic/versions/f0041_docling_document_columns.py`
- Test: (manual upgrade/downgrade verification)

- [ ] **Step 1: Autogenerate the migration**

From `backend/`:

```bash
alembic revision --autogenerate -m "td-0085 docling document columns"
```

Expected: a new file is created under `backend/alembic/versions/`. **Rename it** to `f0041_docling_document_columns.py` and update the `revision = ...` line inside to `revision = "f0041_docling_document_columns"`. Set `down_revision` to the previous head (look at the autogen output for the parent; the most recent head as of writing is `ff7befb11e89` per `alembic heads`).

- [ ] **Step 2: Hand-edit the upgrade()**

Replace the autogen contents with a hand-written version that uses explicit defaults so existing rows don't break:

```python
"""td-0085 docling document columns

Revision ID: f0041_docling_document_columns
Revises: <previous_head>
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa

revision = "f0041_docling_document_columns"
down_revision = "<previous_head>"  # replace with the value alembic autogenerated
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_format", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("stored_markdown", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("images_dir", sa.String(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "refinement_status",
            sa.String(),
            nullable=False,
            server_default="NOT_REQUIRED",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "refinement_flags",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column("documents", sa.Column("ocr_engine", sa.String(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("refined_by_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_documents_refined_by_id_users",
        "documents",
        "users",
        ["refined_by_id"],
        ["id"],
    )
    op.add_column(
        "documents",
        sa.Column("refined_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_constraint("fk_documents_refined_by_id_users", "documents", type_="foreignkey")
    op.drop_column("documents", "refined_at")
    op.drop_column("documents", "refined_by_id")
    op.drop_column("documents", "ocr_engine")
    op.drop_column("documents", "refinement_flags")
    op.drop_column("documents", "refinement_status")
    op.drop_column("documents", "images_dir")
    op.drop_column("documents", "stored_markdown")
    op.drop_column("documents", "source_format")
```

- [ ] **Step 3: Apply, then roll back, then re-apply**

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: each command succeeds. Verify with `psql batchrite -c "\d documents"` that the new columns are present (or absent in the rolled-back state).

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/f0041_docling_document_columns.py
git commit -m "feat(db): migration for docling document columns"
```

---

### Task 7: Extraction job (subprocess) + generic BackgroundHandler

**Files:**
- Create: `backend/app/services/core/background_handler.py`
- Create: `backend/app/services/documents/extraction/extract_job.py`
- Test: `backend/tests/unit/test_background_handler.py`

- [ ] **Step 1: Write the failing handler test**

Create `backend/tests/unit/test_background_handler.py`:

```python
from unittest.mock import patch

import pytest

from app.services.core.background_handler import (
    BackgroundHandler, CloudGpuBackgroundHandler, JOB_REGISTRY,
    LocalBackgroundHandler, get_background_handler, register_job)


def test_factory_returns_local_by_default():
    with patch(
        "app.services.core.background_handler.settings"
    ) as fake_settings:
        fake_settings.background_handler = "local"
        handler = get_background_handler()
    assert isinstance(handler, LocalBackgroundHandler)
    assert isinstance(handler, BackgroundHandler)


def test_factory_returns_cloud_gpu_when_configured():
    with patch(
        "app.services.core.background_handler.settings"
    ) as fake_settings:
        fake_settings.background_handler = "cloud-gpu"
        handler = get_background_handler()
    assert isinstance(handler, CloudGpuBackgroundHandler)


def test_factory_raises_for_unknown_backend():
    with patch(
        "app.services.core.background_handler.settings"
    ) as fake_settings:
        fake_settings.background_handler = "bogus"
        with pytest.raises(ValueError, match="bogus"):
            get_background_handler()


@pytest.mark.asyncio
async def test_cloud_gpu_handler_raises_not_implemented():
    handler = CloudGpuBackgroundHandler()
    with pytest.raises(NotImplementedError):
        await handler.launch("document_extract", document_id="x")


@pytest.mark.asyncio
async def test_local_handler_dispatches_registered_job():
    received: list = []

    @register_job("_fake_job_for_test")
    async def _fake(**kwargs):
        received.append(kwargs)

    submitted: list = []

    class _Runner:
        def submit(self, coro):
            submitted.append(coro)
            # Drive the coroutine to completion so we observe `received`.
            import asyncio
            asyncio.get_event_loop().run_until_complete(coro)

    try:
        with patch(
            "app.services.core.background_handler.get_task_runner",
            return_value=_Runner(),
        ):
            handler = LocalBackgroundHandler()
            await handler.launch("_fake_job_for_test", document_id="abc")
        assert submitted, "task runner should have received a coroutine"
        assert received == [{"document_id": "abc"}]
    finally:
        JOB_REGISTRY.pop("_fake_job_for_test", None)


@pytest.mark.asyncio
async def test_local_handler_raises_for_unknown_job():
    handler = LocalBackgroundHandler()
    with pytest.raises(KeyError, match="nonexistent"):
        await handler.launch("nonexistent")
```

> The `_Runner` fake drives the coroutine inline so we can assert on
> `received`; in production `LocalBackgroundHandler.launch` is
> fire-and-forget (it returns immediately after handing the coroutine
> to the task runner).

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && pytest tests/unit/test_background_handler.py -v`
Expected: ImportError.

- [ ] **Step 3: Write the failing extract_job test**

Create `backend/tests/unit/test_extract_job.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.documents.extraction import extract_job


def _write_artifacts(output_dir: Path, *, markdown: str, image_count: int,
                     page_count: int, flags=None):
    """Simulate what the ext/ script writes when it succeeds."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "refined.md").write_text(markdown)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    for n in range(image_count):
        (output_dir / "images" / f"{n}.png").write_bytes(b"\x89PNG fake")
    (output_dir / "result.json").write_text(json.dumps({
        "page_count": page_count,
        "image_count": image_count,
        "flags": flags or [],
        "ocr_engine": "easyocr",
        "source_format": "PDF",
    }))


@pytest.mark.asyncio
async def test_run_extraction_invokes_subprocess_with_expected_args(tmp_path):
    """The job should exec the configured docling script with --input/--output-dir/--num-threads."""
    captured: dict = {}

    async def _fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        # Write the expected artifacts to simulate a successful run.
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        _write_artifacts(out_dir, markdown="# Hi\n\n![](images/0.png)",
                         image_count=1, page_count=2)
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    fake_doc = MagicMock(
        id=uuid4(), mime_type="application/pdf",
        file_path="uploads/x.pdf",
        page_count=None, status="UPLOADED",
    )

    with patch.object(extract_job, "asyncio") as fake_asyncio, \
         patch.object(extract_job, "_load_and_claim_document",
                      AsyncMock(return_value=(fake_doc, MagicMock()))), \
         patch.object(extract_job, "_persist_success", AsyncMock()) as persist, \
         patch.object(extract_job, "_resolve_paths",
                      return_value=(Path("/tmp/in.pdf"), tmp_path / "out")):
        fake_asyncio.create_subprocess_exec = AsyncMock(side_effect=_fake_exec)
        await extract_job.run_extraction(fake_doc.id)

    argv = captured["argv"]
    assert "--input" in argv
    assert "--output-dir" in argv
    assert "--num-threads" in argv
    persist.assert_awaited()


@pytest.mark.asyncio
async def test_run_extraction_marks_failed_on_nonzero_exit(tmp_path):
    async def _fake_exec(*argv, **kwargs):
        proc = MagicMock()
        proc.returncode = 2
        proc.communicate = AsyncMock(return_value=(b"", b"bad input"))
        return proc

    fake_doc = MagicMock(
        id=uuid4(), mime_type="application/pdf",
        file_path="uploads/x.pdf", status="UPLOADED",
    )

    with patch.object(extract_job, "asyncio") as fake_asyncio, \
         patch.object(extract_job, "_load_and_claim_document",
                      AsyncMock(return_value=(fake_doc, MagicMock()))), \
         patch.object(extract_job, "_persist_failure", AsyncMock()) as fail, \
         patch.object(extract_job, "_persist_success", AsyncMock()) as ok, \
         patch.object(extract_job, "_resolve_paths",
                      return_value=(Path("/tmp/in.pdf"), tmp_path / "out")):
        fake_asyncio.create_subprocess_exec = AsyncMock(side_effect=_fake_exec)
        await extract_job.run_extraction(fake_doc.id)

    fail.assert_awaited()
    ok.assert_not_awaited()
```

> The unit tests mock the subprocess call entirely. Real subprocess invocation is exercised in the integration smoke (Task 15). Backend tests never need docling installed.

- [ ] **Step 4: Run and confirm failure**

Run: `cd backend && pytest tests/unit/test_extract_job.py -v`
Expected: ImportError (module doesn't exist).

- [ ] **Step 5: Create the package marker**

Create empty file: `backend/app/services/documents/extraction/__init__.py`

- [ ] **Step 6: Implement the extract job (subprocess version)**

Create `backend/app/services/documents/extraction/extract_job.py`:

```python
"""Background coroutine that runs the ext/ docling extractor against one document.

The actual docling/torch/easyocr work runs in a subprocess against the
standalone ``ext/docling-extractor/`` project's venv. This module owns
the DB session lifecycle, BackgroundJob row, status transitions, and
artifact ingestion — it never imports docling itself.

Registers under the name "document_extract" via @register_job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from app.core.config import settings
from app.models.jobs import BackgroundJob
from app.models.library import (Document, DocumentSourceFormat, DocumentStatus,
                                RefinementStatus)
from app.services.core.background_handler import register_job
from app.services.core.background_jobs import BackgroundJobService
from app.services.core.file_storage import FileStorageService

logger = logging.getLogger(__name__)


_MIME_TO_FORMAT = {
    "application/pdf": DocumentSourceFormat.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        DocumentSourceFormat.DOCX,
    "image/jpeg": DocumentSourceFormat.IMAGE,
    "image/png": DocumentSourceFormat.IMAGE,
    "image/tiff": DocumentSourceFormat.IMAGE,
    "image/webp": DocumentSourceFormat.IMAGE,
}


def _resolve_paths(doc: Document) -> tuple[Path, Path]:
    """Return (input_file_path, output_dir) for a document.

    The output_dir is per-document, under the storage root, so the
    refined.md / images/ / result.json artifacts land in a predictable
    place that the read endpoints (and the user-facing image URL) can
    point at.
    """
    storage = FileStorageService()
    input_path = storage.resolve_path(doc.file_path)
    output_dir = storage.storage_root / "documents" / str(doc.id)
    return input_path, output_dir


async def _load_and_claim_document(
    session: AsyncSession, document_id: UUID
) -> tuple[Document | None, BackgroundJob | None]:
    """Lock the document row + create the BackgroundJob in one transaction."""
    result = await session.execute(
        select(Document)
        .where(Document.id == document_id)
        .with_for_update(skip_locked=True)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        return None, None

    job = await BackgroundJobService.create(
        session,
        "document_extract",
        "document",
        document_id,
        input_data={"mime_type": doc.mime_type},
    )
    doc.status = DocumentStatus.EXTRACTING.value
    doc.processing_started_at = datetime.now(timezone.utc)
    doc.source_format = _MIME_TO_FORMAT[doc.mime_type].value
    doc.ocr_engine = "easyocr"
    await session.commit()
    return doc, job


async def _persist_success(
    session: AsyncSession,
    doc: Document,
    job: BackgroundJob,
    output_dir: Path,
) -> None:
    """Read artifacts from output_dir and write them to the Document row."""
    result_payload: dict[str, Any] = json.loads(
        (output_dir / "result.json").read_text()
    )
    refined = (output_dir / "refined.md").read_text()
    storage = FileStorageService()

    doc.stored_markdown = refined
    doc.images_dir = str(
        (output_dir / "images").relative_to(storage.storage_root)
    )
    doc.page_count = result_payload.get("page_count")
    doc.refinement_flags = result_payload.get("flags", [])
    flags = doc.refinement_flags
    doc.refinement_status = (
        RefinementStatus.PENDING.value
        if flags
        else RefinementStatus.NOT_REQUIRED.value
    )
    doc.status = DocumentStatus.AWAITING_REFINEMENT.value
    doc.processing_started_at = None

    await BackgroundJobService.complete(
        session,
        job,
        output_data={
            "page_count": doc.page_count,
            "flag_count": len(flags),
            "image_count": result_payload.get("image_count", 0),
        },
    )
    await session.commit()


async def _persist_failure(
    session: AsyncSession,
    document_id: UUID,
    job: BackgroundJob | None,
    message: str,
) -> None:
    await session.rollback()
    result = await session.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if doc is not None:
        doc.status = DocumentStatus.FAILED.value
        doc.error_message = f"Extraction error: {message[:500]}"
        doc.processing_started_at = None
    if job is not None:
        job_result = await session.execute(
            select(BackgroundJob).where(BackgroundJob.id == job.id)
        )
        job = job_result.scalar_one_or_none()
        if job is not None:
            await BackgroundJobService.fail(session, job, message[:500])
    await session.commit()


@register_job("document_extract")
async def run_extraction(document_id: UUID) -> None:
    """Top-level coroutine dispatched by the BackgroundHandler.

    Idempotent: a second pod claiming the same row via SKIP LOCKED
    will find it locked and exit. On success the document transitions
    to AWAITING_REFINEMENT.
    """
    import app.db.base  # noqa: F401 — register model imports

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        doc, job = await _load_and_claim_document(session, document_id)
        if doc is None:
            logger.info("Document %s not found or locked", document_id)
            await engine.dispose()
            return

        input_path, output_dir = _resolve_paths(doc)
        # Clear any prior output (re-run safety)
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            proc = await asyncio.create_subprocess_exec(
                settings.docling_script_python,
                settings.docling_script_path,
                "--input", str(input_path),
                "--output-dir", str(output_dir),
                "--num-threads", str(settings.docling_num_threads),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                msg = stderr.decode(errors="replace") or stdout.decode(
                    errors="replace"
                )
                logger.error(
                    "docling subprocess failed (rc=%s) for %s: %s",
                    proc.returncode, document_id, msg[:500],
                )
                await _persist_failure(session, document_id, job, msg)
                return

            await _persist_success(session, doc, job, output_dir)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Extraction failed for document %s", document_id)
            await _persist_failure(session, document_id, job, str(exc))
        finally:
            await engine.dispose()
```

> **Note:** `FileStorageService.resolve_path` is referenced. It already
> exists on the service — `document_processor.py` calls
> `storage.resolve_path(doc.file_path)`, so verify before adding it.

- [ ] **Step 7: Implement the BackgroundHandler**

Create `backend/app/services/core/background_handler.py`:

```python
"""Generic background-job dispatch abstraction.

Jobs register themselves via `@register_job(name)` and are dispatched
by name through a `BackgroundHandler` implementation. Phase 1 ships
only `LocalBackgroundHandler` (runs in-process via the TaskRunner);
`CloudGpuBackgroundHandler` is a stub so the factory and settings
switch are in place when we move GPU-heavy work to a dedicated
service. Lives in `core/` (next to `task_runner.py`) so it is not
tied to document extraction.

Cloud-gpu serialization note: dispatch is by job-name + kwargs so
the cloud-gpu backend can serialize the call over the wire. Job
kwargs must be JSON-serializable (UUIDs as strings, etc.) when
that backend is enabled. The local backend has no such restriction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict

from app.core.config import settings
from app.services.core.task_runner import get_task_runner

JobFn = Callable[..., Awaitable[None]]

JOB_REGISTRY: Dict[str, JobFn] = {}


def register_job(name: str) -> Callable[[JobFn], JobFn]:
    """Decorator: register a coroutine as a dispatchable background job.

    Usage:
        @register_job("document_extract")
        async def run_extraction(document_id: UUID) -> None:
            ...
    """

    def decorator(fn: JobFn) -> JobFn:
        if name in JOB_REGISTRY and JOB_REGISTRY[name] is not fn:
            raise RuntimeError(f"job {name!r} already registered")
        JOB_REGISTRY[name] = fn
        return fn

    return decorator


class BackgroundHandler(ABC):
    @abstractmethod
    async def launch(self, job: str, **kwargs: Any) -> None:
        """Dispatch a registered background job. Fire-and-forget."""
        ...


class LocalBackgroundHandler(BackgroundHandler):
    """Runs jobs in the API pod's thread pool via the TaskRunner."""

    async def launch(self, job: str, **kwargs: Any) -> None:
        if job not in JOB_REGISTRY:
            raise KeyError(f"no job registered under name {job!r}")
        fn = JOB_REGISTRY[job]
        runner = get_task_runner()
        runner.submit(fn(**kwargs))


class CloudGpuBackgroundHandler(BackgroundHandler):
    """Stub. Will dispatch jobs to a remote GPU service by name + kwargs."""

    async def launch(self, job: str, **kwargs: Any) -> None:
        raise NotImplementedError(
            "cloud-gpu background handler not implemented yet"
        )


def get_background_handler() -> BackgroundHandler:
    backend = settings.background_handler
    if backend == "local":
        return LocalBackgroundHandler()
    if backend == "cloud-gpu":
        return CloudGpuBackgroundHandler()
    raise ValueError(f"unknown background_handler: {backend!r}")
```

> **Import order note:** `extract_job.py` imports `register_job` from
> `background_handler`, so `background_handler` must be importable
> on its own (no circular dependency). The registry only populates
> when `extract_job` is imported — make sure something in the app's
> startup path (e.g. `app.api.endpoints.library` importing
> `get_background_handler` *and* `from app.services.documents.extraction import extract_job  # noqa: F401`)
> triggers the registration before the first upload. The cleanest
> place is the same import block in `library.py` that pulls in
> `get_background_handler`.

- [ ] **Step 8: Run tests**

Run: `cd backend && pytest tests/unit/test_background_handler.py tests/unit/test_extract_job.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/core/background_handler.py \
        backend/app/services/documents/extraction/__init__.py \
        backend/app/services/documents/extraction/extract_job.py \
        backend/tests/unit/test_background_handler.py \
        backend/tests/unit/test_extract_job.py
git commit -m "feat(core): generic BackgroundHandler + document_extract subprocess job (TD-0085)"
```

---

### Task 8: Heartbeat & watchdog — fail hung extractions

**Why this task exists:** docling can hang silently — large PDFs with bad encoding, OCR pinwheels, model load errors that don't bubble. Without a heartbeat, a Document sits in `EXTRACTING` forever and the user gets no signal. This task adds a daemon-thread heartbeat in the `ext/` subprocess that POSTs to an internal backend endpoint every ~10s; a watchdog in the backend job kills the subprocess after 3 consecutive missed beats and marks the Document `FAILED`. A late result (subprocess finishing after the watchdog gave up) is discarded by re-checking the row's terminal state before persisting.

**Design notes:**

- **Transport:** stdlib `urllib.request` from a `threading.Thread(daemon=True)` inside the ext/ subprocess. No `requests` dep in `ext/`.
- **Auth:** per-job random token (`secrets.token_urlsafe(32)`) written to `Document.heartbeat_token` when the job starts; ext/ passes it back in `X-Heartbeat-Token`. Endpoint compares against the stored token in constant time. Token is **cleared** on any terminal state so a zombie subprocess gets a 403.
- **Storage:** `Document.last_heartbeat_at` (timestamp). DB-backed (not in-memory): durable across pod restarts, ready for cloud-gpu, and the watchdog queries it through the same DB session it uses for state transitions.
- **Watchdog cadence:** polls `last_heartbeat_at` every `extraction_heartbeat_interval_seconds`. A "miss" is when the timestamp is `NULL` or unchanged from the prior poll. After `extraction_heartbeat_max_misses` consecutive misses → `proc.kill()` and mark FAILED.
- **Late-result discard:** `_persist_success` re-reads `refinement_status` inside its session; if already `FAILED`, the artifacts in `output_dir` are removed and the function returns. No "winner-takes-all" race.

**Files:**
- Modify: `backend/app/core/config.py` (heartbeat settings)
- Modify: `backend/app/models/library.py` (add `heartbeat_token`, `last_heartbeat_at`)
- Create: `backend/alembic/versions/<rev>_add_extraction_heartbeat_columns.py`
- Create: `backend/app/api/endpoints/internal.py` (or extend `library.py` — see Step 4)
- Create: `backend/app/services/documents/extraction/heartbeat_watchdog.py`
- Modify: `backend/app/services/documents/extraction/extract_job.py` (start watchdog, pass `--heartbeat-*` to subprocess, late-discard in `_persist_success`)
- Create: `ext/docling-extractor/docling_extractor/heartbeat.py`
- Modify: `ext/docling-extractor/extract.py` (CLI args + start the thread)
- Test: `backend/tests/unit/test_heartbeat_endpoint.py`
- Test: `backend/tests/unit/test_heartbeat_watchdog.py`
- Test: `backend/tests/unit/test_extract_job.py` (extend with late-discard case)
- Test: `ext/docling-extractor/tests/test_heartbeat.py`

- [ ] **Step 1: Add heartbeat settings**

Append to `Settings` in `backend/app/core/config.py`:

```python
extraction_heartbeat_interval_seconds: int = 10
extraction_heartbeat_max_misses: int = 3
extraction_heartbeat_base_url: str = "http://localhost:8000"
```

`extraction_heartbeat_base_url` is the URL the **subprocess** uses to call back into the API (it's not the public origin — for local dev this is `http://localhost:8000` because the LocalBackgroundHandler runs in the same pod that serves the API).

- [ ] **Step 2: Add `heartbeat_token` and `last_heartbeat_at` columns to Document**

Edit `backend/app/models/library.py` — add after `refinement_status`:

```python
heartbeat_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)
last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

Generate the additive migration:

```bash
cd backend && alembic revision --autogenerate -m "add extraction heartbeat columns"
```

Review and hand-edit `upgrade()` if necessary to confirm both columns are nullable with no `server_default`. Then `alembic upgrade head` and verify with `psql batchrite -c "\d documents"`.

- [ ] **Step 3: Write the failing endpoint test**

Create `backend/tests/unit/test_heartbeat_endpoint.py`:

```python
"""Heartbeat receiver endpoint — token check + last_heartbeat_at update."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.library import Document


@pytest.mark.asyncio
async def test_heartbeat_updates_last_heartbeat_at(async_session, seed_document_extracting):
    doc: Document = seed_document_extracting
    doc.heartbeat_token = "test-token-abc"
    await async_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/internal/extraction/{doc.id}/heartbeat",
            json={"ts": datetime.now(timezone.utc).isoformat()},
            headers={"X-Heartbeat-Token": "test-token-abc"},
        )

    assert resp.status_code == 200
    await async_session.refresh(doc)
    assert doc.last_heartbeat_at is not None


@pytest.mark.asyncio
async def test_heartbeat_rejects_bad_token(async_session, seed_document_extracting):
    doc: Document = seed_document_extracting
    doc.heartbeat_token = "real-token"
    await async_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/internal/extraction/{doc.id}/heartbeat",
            json={"ts": datetime.now(timezone.utc).isoformat()},
            headers={"X-Heartbeat-Token": "wrong-token"},
        )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_heartbeat_rejects_unknown_document():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/internal/extraction/{uuid.uuid4()}/heartbeat",
            json={"ts": datetime.now(timezone.utc).isoformat()},
            headers={"X-Heartbeat-Token": "anything"},
        )

    assert resp.status_code == 404
```

> `seed_document_extracting` is a fixture that creates a Document row with `extraction_status="EXTRACTING"`. If it doesn't exist in `conftest.py`, add it there following the existing seed-fixture pattern.

Run: `cd backend && pytest tests/unit/test_heartbeat_endpoint.py -v`
Expected: 3 × FAIL (`404 Not Found` because the route isn't registered yet).

- [ ] **Step 4: Implement the heartbeat endpoint**

Create `backend/app/api/endpoints/internal.py`:

```python
"""Internal endpoints — only called by trusted in-process subprocesses
(the ext/docling-extractor heartbeat thread today; future cloud-gpu
workers tomorrow). These routes are NOT for clients and are excluded
from the OpenAPI schema.

Auth model: per-job random token written to the Document row when
the job starts, passed back by the worker in X-Heartbeat-Token, and
cleared on any terminal state. There is no JWT here — the token IS
the credential, scoped to one document for one extraction attempt.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.library import Document

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


class HeartbeatPayload(BaseModel):
    ts: str  # ISO-8601 from the worker; we use server time for the column


@router.post("/extraction/{document_id}/heartbeat")
async def extraction_heartbeat(
    document_id: UUID,
    payload: HeartbeatPayload,
    x_heartbeat_token: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    stored = doc.heartbeat_token or ""
    if not hmac.compare_digest(stored, x_heartbeat_token):
        raise HTTPException(status_code=403, detail="invalid heartbeat token")
    doc.last_heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}
```

Wire it in `backend/app/api/router.py`:

```python
from app.api.endpoints import internal
api_router.include_router(internal.router)
```

Run: `cd backend && pytest tests/unit/test_heartbeat_endpoint.py -v`
Expected: 3 × PASS.

- [ ] **Step 5: Write the failing heartbeat-thread test (ext/)**

Create `ext/docling-extractor/tests/test_heartbeat.py`:

```python
"""Heartbeat thread fires periodic POSTs; stops cleanly on signal."""

from __future__ import annotations

import http.server
import socketserver
import threading
import time
from unittest.mock import patch

from docling_extractor.heartbeat import HeartbeatPoster


class _CountingHandler(http.server.BaseHTTPRequestHandler):
    hits: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.hits.append({"path": self.path, "token": self.headers.get("X-Heartbeat-Token"), "body": body})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *args, **kwargs):  # silence
        pass


def _serve(port: int) -> socketserver.TCPServer:
    httpd = socketserver.TCPServer(("127.0.0.1", port), _CountingHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def test_heartbeat_thread_posts_at_interval(tmp_path):
    _CountingHandler.hits = []
    httpd = _serve(0)
    port = httpd.server_address[1]
    try:
        poster = HeartbeatPoster(
            url=f"http://127.0.0.1:{port}/internal/extraction/abc/heartbeat",
            token="t-1",
            interval_seconds=0.2,
        )
        poster.start()
        time.sleep(0.7)
        poster.stop()
    finally:
        httpd.shutdown()

    assert len(_CountingHandler.hits) >= 2
    assert all(h["token"] == "t-1" for h in _CountingHandler.hits)
    assert all(h["path"] == "/internal/extraction/abc/heartbeat" for h in _CountingHandler.hits)


def test_heartbeat_thread_swallows_network_errors():
    poster = HeartbeatPoster(
        url="http://127.0.0.1:1/no-server",  # nothing listening
        token="t-2",
        interval_seconds=0.1,
    )
    poster.start()
    time.sleep(0.3)
    poster.stop()  # must not raise
```

Run: `cd ext/docling-extractor && .venv/bin/pytest tests/test_heartbeat.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docling_extractor.heartbeat'`.

- [ ] **Step 6: Implement the heartbeat module**

Create `ext/docling-extractor/docling_extractor/heartbeat.py`:

```python
"""Daemon-thread heartbeat poster for the extractor subprocess.

Posts an empty-ish JSON body to a URL on a fixed interval, including
a token header. All network errors are swallowed — the backend's
watchdog is the source of truth for liveness; if a POST fails, the
next POST will succeed or the watchdog will time us out. No backoff,
no retries, no metrics. Keep this tiny."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


class HeartbeatPoster:
    def __init__(self, url: str, token: str, interval_seconds: float) -> None:
        self._url = url
        self._token = token
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        # First beat goes immediately so the watchdog sees us within
        # one poll interval instead of two.
        self._post_once()
        while not self._stop.wait(self._interval):
            self._post_once()

    def _post_once(self) -> None:
        body = json.dumps({"ts": datetime.now(timezone.utc).isoformat()}).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Heartbeat-Token": self._token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5):
                pass
        except (urllib.error.URLError, OSError, TimeoutError):
            return  # backend is unreachable or slow — try again next tick
```

Run: `cd ext/docling-extractor && .venv/bin/pytest tests/test_heartbeat.py -v`
Expected: 2 × PASS.

- [ ] **Step 7: Wire heartbeat into the ext/ CLI**

Edit `ext/docling-extractor/extract.py` — add CLI args and start/stop the poster around `run_pipeline(...)`:

```python
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="docling-based PDF/DOCX extractor")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--num-threads", type=int, default=4)
    # heartbeat (all three required together; all-optional means "no heartbeat")
    parser.add_argument("--heartbeat-url", type=str, default=None)
    parser.add_argument("--heartbeat-token", type=str, default=None)
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
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
        except Exception as exc:
            print(f"extraction failed: {exc}", file=sys.stderr)
            return 1

        args.output_dir.mkdir(parents=True, exist_ok=True)
        images_dir = args.output_dir / "images"
        externalize_images(result.pictures, images_dir)
        refined_md = rewrite_markdown_image_refs(result.markdown, result.pictures)
        (args.output_dir / "refined.md").write_text(refined_md)
        payload = {
            "page_count": result.page_count,
            "image_count": len(result.pictures),
            "flags": result.flags,
            "ocr_engine": "easyocr",
            "source_format": result.source_format,
        }
        (args.output_dir / "result.json").write_text(json.dumps(payload, indent=2))
        return 0
    finally:
        if poster is not None:
            poster.stop()
```

> The heartbeat is started **before** `run_pipeline` and stopped in a `finally` block — so a thrown exception during extraction still cleanly tears down the thread and won't keep the process alive past `sys.exit`.

Add the import: `from docling_extractor.heartbeat import HeartbeatPoster`.

Run: `cd ext/docling-extractor && .venv/bin/pytest tests/ -v`
Expected: all PASS (existing tests + heartbeat tests).

- [ ] **Step 8: Write the failing watchdog test**

Create `backend/tests/unit/test_heartbeat_watchdog.py`:

```python
"""Watchdog kills the subprocess after N consecutive missed heartbeats
and marks the Document FAILED."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.documents.extraction.heartbeat_watchdog import HeartbeatWatchdog


@pytest.mark.asyncio
async def test_watchdog_kills_after_max_misses(async_session, seed_document_extracting):
    doc = seed_document_extracting
    doc.heartbeat_token = "tok"
    doc.last_heartbeat_at = None  # never beat
    await async_session.commit()

    proc = MagicMock()
    proc.returncode = None
    proc.kill = MagicMock()

    watchdog = HeartbeatWatchdog(
        document_id=doc.id,
        proc=proc,
        interval_seconds=0.05,
        max_misses=3,
        session_factory=lambda: async_session,
    )
    await watchdog.run_until_dead_or_done()

    assert proc.kill.called
    assert watchdog.timed_out is True


@pytest.mark.asyncio
async def test_watchdog_resets_on_fresh_heartbeat(async_session, seed_document_extracting):
    doc = seed_document_extracting
    doc.heartbeat_token = "tok"
    doc.last_heartbeat_at = datetime.now(timezone.utc)
    await async_session.commit()

    proc = MagicMock()
    proc.returncode = None
    proc.kill = MagicMock()

    async def bump_heartbeat():
        await asyncio.sleep(0.07)
        doc.last_heartbeat_at = datetime.now(timezone.utc)
        await async_session.commit()

    watchdog = HeartbeatWatchdog(
        document_id=doc.id,
        proc=proc,
        interval_seconds=0.05,
        max_misses=3,
        session_factory=lambda: async_session,
    )

    async def stop_after_short_run():
        await asyncio.sleep(0.4)
        proc.returncode = 0  # subprocess "exited normally"

    await asyncio.gather(watchdog.run_until_dead_or_done(), bump_heartbeat(), stop_after_short_run())

    assert not proc.kill.called
    assert watchdog.timed_out is False
```

Run: `cd backend && pytest tests/unit/test_heartbeat_watchdog.py -v`
Expected: 2 × FAIL (`ModuleNotFoundError`).

- [ ] **Step 9: Implement the watchdog**

Create `backend/app/services/documents/extraction/heartbeat_watchdog.py`:

```python
"""Async watchdog that fails extractions whose subprocess stops sending
heartbeats. Polls Document.last_heartbeat_at every `interval_seconds`;
after `max_misses` consecutive polls with no fresh timestamp, kills the
subprocess. Caller is responsible for marking the row FAILED.

Termination conditions (any → exit the loop):
  - subprocess has exited (proc.returncode is not None) → timed_out=False
  - max_misses reached                                  → timed_out=True
  - external cancellation via stop()                    → timed_out=False
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import Document

logger = logging.getLogger(__name__)


class HeartbeatWatchdog:
    def __init__(
        self,
        *,
        document_id: UUID,
        proc,  # asyncio.subprocess.Process — typed loosely for testability
        interval_seconds: float,
        max_misses: int,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self._document_id = document_id
        self._proc = proc
        self._interval = interval_seconds
        self._max_misses = max_misses
        self._session_factory = session_factory
        self._stop = asyncio.Event()
        self.timed_out = False

    def stop(self) -> None:
        self._stop.set()

    async def run_until_dead_or_done(self) -> None:
        misses = 0
        last_seen: datetime | None = None
        while not self._stop.is_set():
            if self._proc.returncode is not None:
                return  # subprocess finished on its own
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return
            except asyncio.TimeoutError:
                pass

            current = await self._read_heartbeat()
            if current is None or current == last_seen:
                misses += 1
                logger.debug(
                    "heartbeat miss %d/%d for document %s",
                    misses, self._max_misses, self._document_id,
                )
            else:
                misses = 0
                last_seen = current

            if misses >= self._max_misses:
                self.timed_out = True
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
                return

    async def _read_heartbeat(self) -> datetime | None:
        session = self._session_factory()
        try:
            result = await session.execute(
                select(Document.last_heartbeat_at).where(Document.id == self._document_id)
            )
            return result.scalar_one_or_none()
        finally:
            # Tests pass an existing session; the production caller creates one per call.
            # We never close the session here — ownership belongs to the factory.
            pass
```

Run: `cd backend && pytest tests/unit/test_heartbeat_watchdog.py -v`
Expected: 2 × PASS.

- [ ] **Step 10: Wire watchdog + heartbeat token into `extract_job.py`**

Modify `backend/app/services/documents/extraction/extract_job.py`:

1. In `_load_and_claim_document`, generate a heartbeat token and persist it:

```python
import secrets
# ...
doc.heartbeat_token = secrets.token_urlsafe(32)
doc.last_heartbeat_at = None
await session.commit()
```

2. In `run_extraction`, build the heartbeat URL, pass `--heartbeat-*` args, and run the watchdog **concurrently** with `proc.communicate()`:

```python
from app.services.documents.extraction.heartbeat_watchdog import HeartbeatWatchdog
# ...
heartbeat_url = (
    f"{settings.extraction_heartbeat_base_url.rstrip('/')}"
    f"/internal/extraction/{document_id}/heartbeat"
)

proc = await asyncio.create_subprocess_exec(
    settings.docling_script_python,
    settings.docling_script_path,
    "--input", str(input_path),
    "--output-dir", str(output_dir),
    "--num-threads", str(settings.docling_num_threads),
    "--heartbeat-url", heartbeat_url,
    "--heartbeat-token", doc.heartbeat_token,
    "--heartbeat-interval-seconds", str(settings.extraction_heartbeat_interval_seconds),
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)

watchdog = HeartbeatWatchdog(
    document_id=document_id,
    proc=proc,
    interval_seconds=settings.extraction_heartbeat_interval_seconds,
    max_misses=settings.extraction_heartbeat_max_misses,
    session_factory=session_factory,  # AsyncSession factory created in run_extraction
)
watchdog_task = asyncio.create_task(watchdog.run_until_dead_or_done())

try:
    stdout, stderr = await proc.communicate()
finally:
    watchdog.stop()
    await watchdog_task

if watchdog.timed_out:
    await _persist_failure(
        session, document_id, job,
        "Extraction process became unresponsive "
        f"(no heartbeat for {settings.extraction_heartbeat_interval_seconds * settings.extraction_heartbeat_max_misses}s)",
    )
    return

if proc.returncode != 0:
    msg = stderr.decode(errors="replace") or stdout.decode(errors="replace")
    await _persist_failure(session, document_id, job, msg)
    return

await _persist_success(session, doc, job, output_dir)
```

3. Clear the heartbeat token on **both** terminal paths (`_persist_success` and `_persist_failure`):

```python
doc.heartbeat_token = None
```

4. Add late-result discard at the top of `_persist_success`:

```python
async def _persist_success(session, doc, job, output_dir):
    # Re-read terminal state inside our session — the watchdog may have
    # already marked us FAILED while the subprocess was finishing up.
    await session.refresh(doc)
    if doc.refinement_status == RefinementStatus.FAILED.value:
        # Watchdog won the race. Drop the artifacts and bail.
        shutil.rmtree(output_dir, ignore_errors=True)
        return
    # ...existing success persistence...
```

- [ ] **Step 11: Extend `test_extract_job.py` with the late-discard case**

Append to `backend/tests/unit/test_extract_job.py`:

```python
@pytest.mark.asyncio
async def test_late_success_is_discarded_if_watchdog_already_failed(
    async_session, seed_document_extracting, tmp_path, monkeypatch
):
    """Subprocess finishes rc=0 but the doc was already marked FAILED
    by the watchdog. The artifacts should be removed and the row left
    in its FAILED state."""
    doc = seed_document_extracting
    doc.refinement_status = RefinementStatus.FAILED.value
    doc.heartbeat_token = "tok"
    await async_session.commit()

    output_dir = tmp_path / str(doc.id)
    output_dir.mkdir()
    (output_dir / "refined.md").write_text("# hello")
    (output_dir / "result.json").write_text('{"page_count": 1, "image_count": 0, "flags": [], "ocr_engine": "easyocr", "source_format": "pdf"}')

    # Drive _persist_success directly (the integration path is exercised in the smoke test)
    from app.services.documents.extraction import extract_job as ej
    await ej._persist_success(async_session, doc, job=None, output_dir=output_dir)

    await async_session.refresh(doc)
    assert doc.refinement_status == RefinementStatus.FAILED.value
    assert not output_dir.exists()
```

- [ ] **Step 12: Run all tests for the heartbeat slice**

```bash
cd backend && pytest tests/unit/test_heartbeat_endpoint.py tests/unit/test_heartbeat_watchdog.py tests/unit/test_extract_job.py -v
cd ../ext/docling-extractor && .venv/bin/pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 13: Commit**

```bash
git add backend/app/core/config.py \
        backend/app/models/library.py \
        backend/alembic/versions/*_add_extraction_heartbeat_columns.py \
        backend/app/api/endpoints/internal.py \
        backend/app/api/router.py \
        backend/app/services/documents/extraction/heartbeat_watchdog.py \
        backend/app/services/documents/extraction/extract_job.py \
        backend/tests/unit/test_heartbeat_endpoint.py \
        backend/tests/unit/test_heartbeat_watchdog.py \
        backend/tests/unit/test_extract_job.py \
        ext/docling-extractor/docling_extractor/heartbeat.py \
        ext/docling-extractor/extract.py \
        ext/docling-extractor/tests/test_heartbeat.py
git commit -m "feat(extraction): heartbeat + watchdog for hung-extractor detection (TD-0085)"
```

---

### Task 9: Source-page renderer (pymupdf)

**Files:**
- Create: `backend/app/services/documents/extraction/source_page.py`
- Test: `backend/tests/unit/test_source_page.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_source_page.py`:

```python
from pathlib import Path

import pymupdf
import pytest

from app.services.documents.extraction.source_page import render_source_page


def _make_pdf(path: Path, page_count: int) -> None:
    doc = pymupdf.open()
    for _ in range(page_count):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def test_render_source_page_returns_png_bytes(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    _make_pdf(pdf, page_count=2)
    png = render_source_page(pdf, page_number=1, dpi=72)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_source_page_raises_for_out_of_range(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    _make_pdf(pdf, page_count=2)
    with pytest.raises(ValueError, match="page 99"):
        render_source_page(pdf, page_number=99)
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && pytest tests/unit/test_source_page.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `backend/app/services/documents/extraction/source_page.py`:

```python
"""Renders one PDF page to PNG bytes for the editor's left-rail thumbnail."""

from pathlib import Path


def render_source_page(pdf_path: Path, page_number: int, dpi: int = 96) -> bytes:
    """Return PNG bytes for page `page_number` (1-indexed) of a PDF.

    Raises ValueError if the page is out of range. Uses pymupdf which
    is already a runtime dependency.
    """
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(
                f"page {page_number} out of range (1..{len(doc)})"
            )
        page = doc[page_number - 1]
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png")
    finally:
        doc.close()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/test_source_page.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/documents/extraction/source_page.py \
        backend/tests/unit/test_source_page.py
git commit -m "feat(extraction): pymupdf source-page renderer for editor thumbnails"
```

---

### Task 10: Refinement service (state transitions)

**Files:**
- Create: `backend/app/services/documents/refinement/__init__.py` (empty)
- Create: `backend/app/services/documents/refinement/refinement_service.py`
- Test: `backend/tests/unit/test_refinement_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_refinement_service.py`:

```python
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.library import DocumentStatus, RefinementStatus
from app.services.documents.refinement.refinement_service import (
    mark_complete, mark_in_progress, save_markdown)


def _doc(refinement_status=RefinementStatus.PENDING.value):
    d = MagicMock()
    d.id = uuid4()
    d.refinement_status = refinement_status
    d.status = DocumentStatus.AWAITING_REFINEMENT.value
    d.stored_markdown = "old"
    d.refined_by_id = None
    d.refined_at = None
    return d


@pytest.mark.asyncio
async def test_save_markdown_writes_and_marks_in_progress():
    db = AsyncMock()
    doc = _doc()
    await save_markdown(db, doc, "new markdown", user_id=uuid4())
    assert doc.stored_markdown == "new markdown"
    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_save_markdown_skips_state_change_when_already_in_progress():
    db = AsyncMock()
    doc = _doc(refinement_status=RefinementStatus.IN_PROGRESS.value)
    await save_markdown(db, doc, "another edit", user_id=uuid4())
    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_mark_in_progress_idempotent():
    db = AsyncMock()
    doc = _doc()
    await mark_in_progress(db, doc)
    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value
    # second call: still IN_PROGRESS
    await mark_in_progress(db, doc)
    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_mark_complete_sets_indexing_and_stamps_user():
    db = AsyncMock()
    doc = _doc()
    uid = uuid4()
    await mark_complete(db, doc, user_id=uid)
    assert doc.refinement_status == RefinementStatus.COMPLETE.value
    assert doc.status == DocumentStatus.INDEXING.value
    assert doc.refined_by_id == uid
    assert isinstance(doc.refined_at, datetime)


@pytest.mark.asyncio
async def test_mark_complete_rejects_already_complete():
    db = AsyncMock()
    doc = _doc(refinement_status=RefinementStatus.COMPLETE.value)
    with pytest.raises(ValueError, match="already complete"):
        await mark_complete(db, doc, user_id=uuid4())
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && pytest tests/unit/test_refinement_service.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `backend/app/services/documents/refinement/__init__.py` (empty file).

Create `backend/app/services/documents/refinement/refinement_service.py`:

```python
"""Document refinement state transitions.

These are the only writes allowed against refinement_status /
refined_by_id / refined_at. Endpoints call these; they raise
ValueError on disallowed transitions and the endpoint layer converts
to HTTP 409.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import (Document, DocumentStatus, RefinementStatus)


async def mark_in_progress(db: AsyncSession, doc: Document) -> None:
    if doc.refinement_status in (
        RefinementStatus.NOT_REQUIRED.value,
        RefinementStatus.PENDING.value,
    ):
        doc.refinement_status = RefinementStatus.IN_PROGRESS.value
    # else: IN_PROGRESS stays, COMPLETE stays (caller should re-open
    # explicitly)


async def save_markdown(
    db: AsyncSession,
    doc: Document,
    markdown: str,
    user_id: UUID,
) -> None:
    doc.stored_markdown = markdown
    await mark_in_progress(db, doc)


async def mark_complete(
    db: AsyncSession, doc: Document, user_id: UUID
) -> None:
    if doc.refinement_status == RefinementStatus.COMPLETE.value:
        raise ValueError("Document refinement already complete")
    doc.refinement_status = RefinementStatus.COMPLETE.value
    doc.status = DocumentStatus.INDEXING.value
    doc.refined_by_id = user_id
    doc.refined_at = datetime.now(timezone.utc)


async def reopen(db: AsyncSession, doc: Document) -> None:
    if doc.refinement_status != RefinementStatus.COMPLETE.value:
        raise ValueError("Only completed refinements can be re-opened")
    doc.refinement_status = RefinementStatus.IN_PROGRESS.value
    doc.status = DocumentStatus.AWAITING_REFINEMENT.value
    doc.refined_by_id = None
    doc.refined_at = None
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/test_refinement_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/documents/refinement/__init__.py \
        backend/app/services/documents/refinement/refinement_service.py \
        backend/tests/unit/test_refinement_service.py
git commit -m "feat(refinement): state transitions for document refinement"
```

---

### Task 11: AI-fix service

**Files:**
- Create: `backend/app/services/documents/refinement/ai_fix.py`
- Test: `backend/tests/unit/test_refinement_ai_fix.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_refinement_ai_fix.py`:

```python
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.documents.refinement.ai_fix import (RefineAiPayload,
                                                      apply_ai_fix)


@pytest.mark.asyncio
async def test_apply_ai_fix_returns_suggested_markdown():
    payload = RefineAiPayload(
        scope="selection",
        selection_markdown="NaHzPO4119.98",
        instruction="Fix OCR artifact",
    )
    fake_agent = MagicMock()
    fake_run = MagicMock()
    fake_run.output = "NaH2PO4 119.98"
    fake_agent.run = AsyncMock(return_value=fake_run)

    with patch(
        "app.services.documents.refinement.ai_fix.get_model",
        AsyncMock(return_value="anthropic:claude-sonnet-4-5-20250929"),
    ), patch(
        "app.services.documents.refinement.ai_fix.Agent",
        return_value=fake_agent,
    ), patch(
        "app.services.documents.refinement.ai_fix.get_model_display_name",
        AsyncMock(return_value="claude-sonnet-4-5-20250929"),
    ):
        result = await apply_ai_fix(
            db=MagicMock(),
            document_id=uuid4(),
            org_id=uuid4(),
            payload=payload,
        )

    assert result.suggested_markdown == "NaH2PO4 119.98"
    assert "claude" in result.model_used


@pytest.mark.asyncio
async def test_apply_ai_fix_includes_surrounding_context_in_prompt():
    payload = RefineAiPayload(
        scope="block",
        selection_markdown="cell text",
        instruction="fix the cell",
        surrounding_context_markdown="...before... |cell text| ...after...",
    )
    captured: dict = {}
    fake_agent = MagicMock()

    async def _run(prompt):
        captured["prompt"] = prompt
        r = MagicMock()
        r.output = "fixed cell"
        return r

    fake_agent.run = _run

    with patch(
        "app.services.documents.refinement.ai_fix.get_model",
        AsyncMock(return_value="x"),
    ), patch(
        "app.services.documents.refinement.ai_fix.Agent",
        return_value=fake_agent,
    ), patch(
        "app.services.documents.refinement.ai_fix.get_model_display_name",
        AsyncMock(return_value="x"),
    ):
        await apply_ai_fix(
            db=MagicMock(),
            document_id=uuid4(),
            org_id=uuid4(),
            payload=payload,
        )

    assert "...before..." in captured["prompt"]
    assert "cell text" in captured["prompt"]
    assert "fix the cell" in captured["prompt"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && pytest tests/unit/test_refinement_ai_fix.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `backend/app/services/documents/refinement/ai_fix.py`:

```python
"""Selection-scoped AI refinement of extracted markdown.

Calls the `document_refinement` capability via `get_model()`. No
business logic beyond prompt assembly + sanitization. Endpoint code
catches exceptions and converts to HTTP errors.
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from pydantic_ai import Agent
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.ai_config import get_model, get_model_display_name

_SYSTEM_PROMPT = (
    "You are correcting OCR / layout-extraction artifacts in scientific "
    "documents. Return only the corrected markdown for the selection — "
    "no preamble, no explanation, no surrounding context."
)


@dataclass
class RefineAiPayload:
    scope: str  # "selection" | "block" | "document"
    selection_markdown: str
    instruction: str
    surrounding_context_markdown: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[list[float]] = None


@dataclass
class RefineAiResult:
    suggested_markdown: str
    model_used: str


def _build_prompt(payload: RefineAiPayload) -> str:
    parts: list[str] = []
    parts.append(f"Instruction: {payload.instruction}")
    if payload.surrounding_context_markdown:
        parts.append(
            "Surrounding context (do not modify, just for grounding):\n"
            f"{payload.surrounding_context_markdown}"
        )
    parts.append("Selection to correct:")
    parts.append(payload.selection_markdown)
    return "\n\n".join(parts)


async def apply_ai_fix(
    db: AsyncSession,
    document_id: UUID,
    org_id: UUID,
    payload: RefineAiPayload,
) -> RefineAiResult:
    model = await get_model("document_refinement", db, org_id=org_id)
    agent = Agent(model, system_prompt=_SYSTEM_PROMPT)
    run = await agent.run(_build_prompt(payload))
    suggested = (run.output or "").strip()
    model_name = await get_model_display_name(
        "document_refinement", db, org_id=org_id
    )
    return RefineAiResult(
        suggested_markdown=suggested, model_used=model_name
    )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/test_refinement_ai_fix.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/documents/refinement/ai_fix.py \
        backend/tests/unit/test_refinement_ai_fix.py
git commit -m "feat(refinement): selection-scoped AI fix via document_refinement capability"
```

---

### Task 12: Indexing trigger — chunk refined markdown

**Files:**
- Modify: `backend/app/services/documents/markdown_chunker.py`
- Create: `backend/app/services/documents/refinement/indexing.py`
- Test: `backend/tests/unit/test_refinement_indexing.py`

- [ ] **Step 1: Inspect the current chunker**

Run: `grep -n "^def\|^async def" backend/app/services/documents/markdown_chunker.py`
Expected: identify `chunk_markdown`, `chunk_by_pages`, and any `rechunk_with_structure` helpers.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_refinement_indexing.py`:

```python
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.documents.refinement.indexing import index_refined_document


@pytest.mark.asyncio
async def test_index_refined_document_chunks_and_calls_embedder():
    doc = MagicMock()
    doc.id = uuid4()
    doc.org_id = uuid4()
    doc.stored_markdown = "# Heading\n\nBody paragraph.\n"

    db = AsyncMock()
    db.execute = AsyncMock()

    with patch(
        "app.services.documents.refinement.indexing.chunk_markdown",
        return_value=[MagicMock(content="# Heading", chunk_index=0,
                                token_count=2, page_number=None)],
    ), patch(
        "app.services.documents.refinement.indexing.embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    ):
        await index_refined_document(db, doc)

    # one DocumentChunk added
    assert db.add.called
```

- [ ] **Step 3: Run and confirm failure**

Run: `cd backend && pytest tests/unit/test_refinement_indexing.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement the indexer**

Create `backend/app/services/documents/refinement/indexing.py`:

```python
"""Chunks refined markdown into DocumentChunks and embeds them.

Called from the endpoint that marks refinement complete. Replaces
the old build_book + rechunk_with_structure path; the input is the
already-clean refined markdown so there's no need for AI-driven
structure recovery.
"""

import logging
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import (EMBEDDING_DIMENSIONS, Document, DocumentChunk,
                                DocumentStatus)
from app.services.ai.embedding import embed_texts
from app.services.documents.markdown_chunker import chunk_markdown

logger = logging.getLogger(__name__)


def _pad_embedding(vec: list[float]) -> list[float]:
    if len(vec) >= EMBEDDING_DIMENSIONS:
        return vec[:EMBEDDING_DIMENSIONS]
    return list(vec) + [0.0] * (EMBEDDING_DIMENSIONS - len(vec))


async def index_refined_document(
    db: AsyncSession, doc: Document
) -> None:
    """Chunk + embed the refined markdown. Idempotent: drops prior chunks."""
    if not doc.stored_markdown:
        doc.status = DocumentStatus.READY.value
        return

    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    )

    chunks = chunk_markdown(doc.stored_markdown, 1000, 200, None)
    try:
        embeddings = await embed_texts(
            [c.content for c in chunks], db, org_id=doc.org_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Embedding failed for refined doc %s: %s",
            doc.id,
            str(exc)[:200],
        )
        embeddings = []

    for i, chunk in enumerate(chunks):
        emb = _pad_embedding(embeddings[i]) if i < len(embeddings) else None
        db.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                page_number=chunk.page_number,
                chunk_metadata={"content_format": "markdown"},
                embedding=emb,
            )
        )

    doc.status = DocumentStatus.READY.value
```

- [ ] **Step 5: Strip `rechunk_with_structure` and any `doc_structure`-coupled helpers**

In `backend/app/services/documents/markdown_chunker.py`:
- **Delete** any function whose only purpose was to consume `doc_structure` output (look for `rechunk_with_structure`, helpers it called, and any imports it required).
- **Keep** `chunk_markdown` and `chunk_by_pages`.
- After editing, run `grep -n 'doc_structure\|document_structure' backend/app/services/documents/markdown_chunker.py` — expected: 0 hits.

- [ ] **Step 6: Run tests**

Run: `cd backend && pytest tests/unit/test_refinement_indexing.py tests/unit/test_documents_retrieval.py -v`
Expected: refinement test PASSES; retrieval tests should still pass (chunker public API unchanged).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/documents/refinement/indexing.py \
        backend/app/services/documents/markdown_chunker.py \
        backend/tests/unit/test_refinement_indexing.py
git commit -m "feat(refinement): indexer that chunks refined markdown post-refinement"
```

---

### Task 13: API surface — new endpoints + upload swap

**Files:**
- Modify: `backend/app/api/endpoints/library.py`
- Modify: `backend/app/schemas/library.py`
- Test: `backend/tests/integration/test_library_docling.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_library_docling.py`:

```python
import io
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient

# Reuses the conftest fixtures used by test_library_api.py
pytestmark = pytest.mark.asyncio


_PDF_MAGIC = b"%PDF-1.4\n%minimal\n"


async def _upload(client: AsyncClient, headers, content=_PDF_MAGIC):
    files = {"file": ("test.pdf", io.BytesIO(content), "application/pdf")}
    data = {"title": "Test Doc"}
    return await client.post(
        "/api/library/documents", files=files, data=data, headers=headers
    )


async def test_upload_rejects_text_plain(client: AsyncClient, auth_headers):
    files = {"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")}
    data = {"title": "T"}
    resp = await client.post(
        "/api/library/documents", files=files, data=data, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_upload_calls_background_handler(
    client: AsyncClient, auth_headers
):
    launched: list = []

    class _FakeHandler:
        async def launch(self, job, **kwargs):
            launched.append((job, kwargs))

    with patch(
        "app.api.endpoints.library.get_background_handler",
        return_value=_FakeHandler(),
    ):
        resp = await _upload(client, auth_headers)

    assert resp.status_code == 201
    assert len(launched) == 1
    job, kwargs = launched[0]
    assert job == "document_extract"
    assert isinstance(kwargs["document_id"], UUID)


async def test_get_markdown_404_until_extracted(
    client: AsyncClient, auth_headers, fresh_document
):
    # `fresh_document` fixture inserts a Document row with no
    # stored_markdown
    resp = await client.get(
        f"/api/library/documents/{fresh_document.id}/markdown",
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_put_markdown_saves_and_marks_in_progress(
    client: AsyncClient, auth_headers, extracted_document
):
    new_md = "# New title\n\nFresh body."
    resp = await client.put(
        f"/api/library/documents/{extracted_document.id}/markdown",
        json={"markdown": new_md},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["refinement_status"] == "IN_PROGRESS"


async def test_refine_complete_transitions_to_indexing(
    client: AsyncClient, auth_headers, extracted_document
):
    with patch(
        "app.api.endpoints.library.index_refined_document",
        AsyncMock(),
    ):
        resp = await client.post(
            f"/api/library/documents/{extracted_document.id}/refine/complete",
            json={},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] in ("INDEXING", "READY")


async def test_refine_ai_returns_suggested_markdown(
    client: AsyncClient, auth_headers, extracted_document
):
    from app.services.documents.refinement.ai_fix import RefineAiResult

    with patch(
        "app.api.endpoints.library.apply_ai_fix",
        AsyncMock(return_value=RefineAiResult(
            suggested_markdown="fixed",
            model_used="claude-sonnet-4-5-20250929",
        )),
    ):
        resp = await client.post(
            f"/api/library/documents/{extracted_document.id}/refine/ai",
            json={
                "scope": "selection",
                "selection_markdown": "bad",
                "instruction": "fix it",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_markdown"] == "fixed"
    assert body["model_used"].startswith("claude")
```

> Two fixtures (`fresh_document`, `extracted_document`) need to exist. If `backend/tests/integration/conftest.py` doesn't have them, add them — they create one `Document` row, with and without `stored_markdown`/`refinement_status='PENDING'`, scoped to the auth user's org. Mirror the existing `fresh_document` pattern in `test_library_api.py` if present; otherwise add minimal fixtures inside this test file.

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && pytest tests/integration/test_library_docling.py -v`
Expected: all FAIL (endpoints don't exist, fixtures missing).

- [ ] **Step 3: Add schemas**

In `backend/app/schemas/library.py`, append:

```python
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class MarkdownPayload(BaseModel):
    markdown: str


class RefineAiRequest(BaseModel):
    scope: str = Field(..., pattern="^(selection|block|document)$")
    selection_markdown: str
    instruction: str
    surrounding_context_markdown: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[list[float]] = None

    @field_validator("bbox")
    @classmethod
    def _bbox_len(cls, v):
        if v is None:
            return v
        if len(v) != 4:
            raise ValueError("bbox must be [x0,y0,x1,y1]")
        return v


class RefineAiResponse(BaseModel):
    suggested_markdown: str
    model_used: str


class RefineCompleteRequest(BaseModel):
    reopen: bool = False
```

Also: extend `DocumentResponse` and `DocumentDetailResponse` to expose `source_format`, `refinement_status`, `refinement_flags`, `refined_by_id`, `refined_at` (mirror the existing optional-field pattern; use `from_attributes=True`).

- [ ] **Step 4: Rewire the upload endpoint**

In `backend/app/api/endpoints/library.py`:

1. Replace the imports at the top of the file:

```python
# Remove:
from app.services.documents.document_processor import (build_book,
                                                       process_document)
# Add:
from app.services.core.background_handler import get_background_handler
# Import the extract job module so @register_job populates JOB_REGISTRY
# at app startup (this side effect is the registration).
from app.services.documents.extraction import extract_job  # noqa: F401
from app.services.documents.extraction.source_page import \
    render_source_page
from app.services.documents.refinement.ai_fix import (RefineAiPayload,
                                                       apply_ai_fix)
from app.services.documents.refinement.indexing import \
    index_refined_document
from app.services.documents.refinement.refinement_service import (mark_complete,
                                                                   reopen,
                                                                   save_markdown)
from app.schemas.library import (MarkdownPayload, RefineAiRequest,
                                 RefineAiResponse, RefineCompleteRequest)
```

2. Replace the three `get_task_runner().submit(build_book(...))` calls (lines ~204, ~521, ~864 in the current file) with:

```python
await get_background_handler().launch("document_extract", document_id=doc.id)
```

3. Reject `source_url` payloads at upload time. In `upload_document`, after the `mime_type` check, add:

```python
    # Source URL uploads removed in Phase 1 (see TD-0085).
    # source_url is no longer accepted on creation.
    # (no-op here: it is not in the Form() signature; if it ever
    # reappears, raise 422.)
```

4. **Delete** the `enrich_document_endpoint` route (lines 530–566) entirely.

5. **Add** new endpoints below the existing get/list handlers:

```python
@router.get("/documents/{document_id}/markdown")
async def get_document_markdown(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(
        require_permission(ObjectType.DOCUMENT, "document_id", PermissionLevel.VIEW)
    ),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None or doc.stored_markdown is None:
        raise HTTPException(404, "Markdown not available")
    return {"markdown": doc.stored_markdown}


@router.put("/documents/{document_id}/markdown", response_model=DocumentResponse)
async def put_document_markdown(
    document_id: uuid.UUID,
    payload: MarkdownPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(
        require_permission(ObjectType.DOCUMENT, "document_id", PermissionLevel.EDIT)
    ),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Document not found")
    await save_markdown(db, doc, payload.markdown, user_id=current_user.id)
    await db.commit()
    await db.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.post("/documents/{document_id}/refine/ai", response_model=RefineAiResponse)
async def refine_with_ai(
    document_id: uuid.UUID,
    payload: RefineAiRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(
        require_permission(ObjectType.DOCUMENT, "document_id", PermissionLevel.EDIT)
    ),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await apply_ai_fix(
        db,
        document_id,
        org_id,
        RefineAiPayload(**payload.model_dump()),
    )
    return RefineAiResponse(
        suggested_markdown=result.suggested_markdown,
        model_used=result.model_used,
    )


@router.post(
    "/documents/{document_id}/refine/complete",
    response_model=DocumentResponse,
)
async def refine_complete(
    document_id: uuid.UUID,
    payload: RefineCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(
        require_permission(ObjectType.DOCUMENT, "document_id", PermissionLevel.EDIT)
    ),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Document not found")

    if payload.reopen:
        try:
            await reopen(db, doc)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await db.commit()
        await db.refresh(doc)
        return DocumentResponse.model_validate(doc)

    try:
        await mark_complete(db, doc, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await index_refined_document(db, doc)
    await db.commit()
    await db.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.get("/documents/{document_id}/images/{filename}")
async def get_document_image(
    document_id: uuid.UUID,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(
        require_permission(ObjectType.DOCUMENT, "document_id", PermissionLevel.VIEW)
    ),
):
    if not re.fullmatch(r"\d+\.png", filename):
        raise HTTPException(400, "Invalid image filename")
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document.images_dir).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    images_dir = result.scalar_one_or_none()
    if images_dir is None:
        raise HTTPException(404, "Image not found")
    path = FileStorageService().storage_root / images_dir / filename
    if not path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type="image/png")


@router.get("/documents/{document_id}/source-page/{page_number}.png")
async def get_document_source_page(
    document_id: uuid.UUID,
    page_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(
        require_permission(ObjectType.DOCUMENT, "document_id", PermissionLevel.VIEW)
    ),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None or doc.mime_type != "application/pdf":
        raise HTTPException(404, "Source page not available")
    path = FileStorageService().resolve_path(doc.file_path)
    try:
        png = render_source_page(path, page_number)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content=png, media_type="image/png")
```

> Permission dependency note: `require_permission` is imported from `app.core.deps` (check the existing handlers in this file — it's already used). If a particular handler in the file uses an inline `_can_delete_document`-style check instead, mirror that pattern; the goal is a consistent permission gate, not introducing a new one.

- [ ] **Step 5: Run integration tests**

Run: `cd backend && pytest tests/integration/test_library_docling.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full integration suite to catch regressions**

Run: `cd backend && pytest tests/integration -v -x`
Expected: existing tests still pass. The most likely break is `test_library_api.py` if it asserted on `build_book` or `process_document`; fix those tests by swapping to `get_background_handler` patching (matching the `_FakeHandler` pattern in `test_library_docling.py`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/library.py \
        backend/app/schemas/library.py \
        backend/tests/integration/test_library_docling.py
git commit -m "feat(api): docling upload + refinement endpoints (TD-0085)"
```

---

### Task 14: Delete legacy pipeline code

**Files:**
- Delete: `backend/app/services/documents/document_structure.py`
- Modify: `backend/app/services/documents/document_processor.py`
- Run: full unit + integration suite

- [ ] **Step 1: Verify no references remain to legacy functions outside of the file itself**

Run:
```bash
cd backend && grep -rn "build_book\|enrich_document\|process_document\|document_structure" app/ --include="*.py" | grep -v "extraction/\|refinement/"
```
Expected: only matches inside `document_processor.py` and `document_structure.py` themselves. If anything else turns up (notification handlers, recovery service, etc.) wire it to `get_background_handler().launch("document_extract", document_id=...)` before deletion.

- [ ] **Step 2: Delete `document_structure.py`**

```bash
git rm backend/app/services/documents/document_structure.py
```

- [ ] **Step 3: Remove the legacy functions from `document_processor.py`**

In `backend/app/services/documents/document_processor.py`:
- **Delete** `process_document` (lines ~28–337).
- **Delete** `enrich_document` if present.
- **Delete** `build_book` if present.
- **Delete** any helpers (`_extract_pdf_page_range`, `_get_pdf_page_count`, `_extract_pdf_toc`, etc.) that are now unused — verify with `grep -n` first.
- If the resulting file is **empty** (no other public functions), delete it: `git rm backend/app/services/documents/document_processor.py`. If anything legitimate remains, leave the trimmed file.

- [ ] **Step 4: Remove `doc_structure` env fallback handling**

Run `grep -rn "doc_structure" backend/app/ --include="*.py"` — expected hits: zero in `services/`/`api/`. If matches surface in `services/ai/ai_config.py` or similar, remove them (the capability is gone).

- [ ] **Step 5: Run the full test suite**

Run: `cd backend && pytest -x`
Expected: all tests PASS. Fix any straggler import errors by updating imports to the new modules.

- [ ] **Step 6: Verify spec's grep clause**

Run:
```bash
grep -r 'doc_structure\|document_structure' backend/app/services backend/app/api 2>&1
```
Expected: 0 hits.

- [ ] **Step 7: Commit**

```bash
git add -A backend/app
git commit -m "refactor(documents): delete legacy extraction pipeline and doc_structure capability"
```

---

### Task 15: End-to-end smoke against the dev stack

**Files:** none modified. This is a verification step.

- [ ] **Step 1: Boot the worktree backend**

From this worktree:

```bash
cd backend
source .venv/bin/activate
# Confirm docling group is installed in this venv:
poetry install --with docling
alembic upgrade head
uvicorn app.main:app --reload --port 8010
```

- [ ] **Step 2: Upload a small PDF**

In another terminal, with a valid auth token saved in `$TOKEN`:

```bash
curl -X POST http://localhost:8010/api/library/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@scripts/mocks/animal-culture-textbook.pdf;type=application/pdf" \
  -F "title=Smoke test"
```

Expected: `201 Created` with a `DocumentResponse` body. Capture the `id` as `$DOC_ID`.

- [ ] **Step 3: Watch the status transitions**

Poll every few seconds (a textbook will take ~30 min on CPU — for the smoke test, use a small SOP, 5–10 pages):

```bash
curl -s http://localhost:8010/api/library/documents/$DOC_ID \
  -H "Authorization: Bearer $TOKEN" | jq '.status, .refinement_status'
```

Expected sequence: `UPLOADED/QUEUED → EXTRACTING → AWAITING_REFINEMENT` with `refinement_status` ending in `PENDING` or `NOT_REQUIRED`.

- [ ] **Step 4: Fetch the stored markdown**

```bash
curl -s http://localhost:8010/api/library/documents/$DOC_ID/markdown \
  -H "Authorization: Bearer $TOKEN" | jq '.markdown' | head -40
```

Expected: real markdown output with headings, paragraphs, and `![](images/...)` references.

- [ ] **Step 5: Save an edit**

```bash
curl -X PUT http://localhost:8010/api/library/documents/$DOC_ID/markdown \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"markdown": "# Edited title\n\nBody."}'
```

Expected: 200 OK; the returned `refinement_status` is `IN_PROGRESS`.

- [ ] **Step 6: Mark complete and verify indexing**

```bash
curl -X POST http://localhost:8010/api/library/documents/$DOC_ID/refine/complete \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Expected: 200 OK; the returned `status` is `INDEXING` then transitions to `READY`. Verify chunks were created:

```bash
curl -s http://localhost:8010/api/library/documents/$DOC_ID \
  -H "Authorization: Bearer $TOKEN" | jq '.chunk_count'
```

Expected: ≥ 1.

- [ ] **Step 7: Fetch one image**

```bash
curl -s http://localhost:8010/api/library/documents/$DOC_ID/images/0.png \
  -H "Authorization: Bearer $TOKEN" -o /tmp/img0.png
file /tmp/img0.png
```

Expected: `PNG image data, ...`.

- [ ] **Step 8: Final commit (no code changes — verification only)**

Nothing to commit. If you uncovered a real bug during smoke testing, fix it in a separate task and commit; do not bundle here.

---

## Self-Review Notes

**Spec coverage:**
- Standalone `ext/docling-extractor/` project (scaffold + CLI) → Tasks 1 + 2.
- Schema changes → Task 5 (model) + Task 6 (migration).
- AI capability registration → Task 4.
- Docling/background_handler settings → Task 3.
- Job infrastructure (generic BackgroundHandler + subprocess extract job) → Task 7.
- Image externalization → Task 2 (inside the ext/ CLI — backend is hands-off).
- Heartbeat + watchdog (hung-job detection, late-result discard, internal heartbeat endpoint) → Task 8.
- Source-page rendering → Task 9.
- Refinement state transitions → Task 10.
- AI-fix path → Task 11.
- Indexing trigger moved to post-refinement → Task 12 (chunker) + Task 13 (`refine/complete` fires it).
- API surface → Task 13.
- Removal of legacy pipeline → Task 14.
- Pass-criteria verification → Task 15.
- `source_url` rejection on uploads → Task 13 (note added; column itself stays in place per spec).

**Out of plan scope (per spec): frontend (Phase 2), cloud-gpu BackgroundHandler implementation, .claude/rules updates, CLAUDE.md updates.**

**Risk: the `DEFAULT_CONFIGS["document_refinement"]` model name.** Task 4 specifies `claude-sonnet-4-5-20250929`. If this model ID isn't in the codebase's `context_window_defaults`, the AI capability will silently fall back to 8192-token context and trigger compaction. Verify against `settings.context_window_defaults` in `config.py` — the existing entry `"claude-sonnet-4": 200000` matches by prefix, so this is safe.

**Risk: `Document.refinement_status` default.** Task 5 sets `default=RefinementStatus.PENDING.value` (for new ORM-created rows) but the migration `server_default="NOT_REQUIRED"` (so existing rows don't show up in the refinement queue). New uploads will be set to PENDING by the extract job once flags are populated; before extraction completes the application default never persists because the extract job overrides it.
