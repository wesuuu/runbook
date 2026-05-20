"""Phase 1 spike: run docling on the test corpus and dump artifacts.

Usage (from backend/):
    python scripts/docling_eval.py

Emits, for each input doc, three artifacts under
``tests/artifacts/docling_out/<stem>/``:
  - output.json  — DoclingDocument dump (structure inspection)
  - output.md    — markdown export (what the chunker will see)
  - output.html  — docling's native HTML (images, columns, figures)

Also writes ``tests/artifacts/docling_out/summary.json`` with timing.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Allow running as a script: ensure `app` is importable.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ai.workflows.document_extraction import (  # noqa: E402
    extract_docx,
    extract_pdf,
    render_html,
)
from app.services.ai.workflows.document_extraction.models import (
    StructuredDoc,
)  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("docling_eval")


CORPUS: list[Path] = [
    BACKEND_ROOT / "tests/artifacts/templates/sop_simple.pdf",
    BACKEND_ROOT / "tests/artifacts/templates/sop_role_based.pdf",
    BACKEND_ROOT / "tests/artifacts/templates/sop_process_based.pdf",
    BACKEND_ROOT / "tests/artifacts/templates/batch_record_blank_simple.pdf",
    BACKEND_ROOT / "tests/artifacts/templates/batch_record_blank_roles.pdf",
    BACKEND_ROOT / "tests/artifacts/templates/batch_record_filled_simple.pdf",
    BACKEND_ROOT / "tests/artifacts/templates/batch_record_filled_figures.pdf",
    BACKEND_ROOT / "tests/artifacts/templates/batch_record_filled_edited_gmp.pdf",
    BACKEND_ROOT / "tests/artifacts/templates/sop_simple.docx",
    BACKEND_ROOT / "tests/artifacts/templates/sop_role_based.docx",
    BACKEND_ROOT / "tests/artifacts/templates/batch_record_filled_simple.docx",
    BACKEND_ROOT / "tests/artifacts/templates/batch_record_filled_figures.docx",
    BACKEND_ROOT / "tests/fixtures/sample_batch_record.pdf",
    BACKEND_ROOT / "tests/benchmarks/document-to-run/02-wrong-protocol/document.pdf",
]

OUT_ROOT = BACKEND_ROOT / "tests/artifacts/docling_out"


def _extract(path: Path) -> StructuredDoc:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix == ".docx":
        return extract_docx(path)
    raise ValueError(f"Unsupported extension: {suffix}")


def _dump_one(path: Path) -> dict:
    if not path.exists():
        logger.warning("skip missing: %s", path)
        return {"path": str(path), "skipped": "missing"}

    # Include suffix to avoid PDF and DOCX with the same stem stomping
    out_dir = OUT_ROOT / f"{path.stem}{path.suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    try:
        doc = _extract(path)
    except Exception as exc:
        logger.exception("extraction failed: %s", path)
        return {"path": str(path), "error": repr(exc)}
    elapsed = time.perf_counter() - started

    # Markdown
    (out_dir / "output.md").write_text(doc.markdown, encoding="utf-8")

    # HTML (docling native — images, columns, figures)
    html = render_html(doc)
    (out_dir / "output.html").write_text(html, encoding="utf-8")

    # JSON dump of DoclingDocument when available
    if doc.raw is not None:
        json_payload: object
        try:
            json_payload = doc.raw.export_to_dict()
        except Exception:
            try:
                json_payload = doc.raw.model_dump(mode="json")
            except Exception as exc:
                json_payload = {"error": f"could not serialize: {exc!r}"}
        (out_dir / "output.json").write_text(
            json.dumps(json_payload, indent=2, default=str), encoding="utf-8"
        )

    summary = {
        "path": str(path.relative_to(BACKEND_ROOT)),
        "stem": path.stem,
        "seconds": round(elapsed, 2),
        "page_count": doc.page_count,
        "markdown_chars": len(doc.markdown),
        "toc_entries": len(doc.toc),
        "page_spans": len(doc.page_spans),
        "html_chars": len(html),
    }
    logger.info(
        "ok %-50s %4ds %3dp %5dh md=%d",
        path.name,
        int(summary["seconds"]),
        summary["page_count"],
        summary["toc_entries"],
        summary["markdown_chars"],
    )
    return summary


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results = [_dump_one(p) for p in CORPUS]

    summary_path = OUT_ROOT / "summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("summary written to %s", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
