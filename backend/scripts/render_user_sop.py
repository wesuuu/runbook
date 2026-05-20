"""Render the user's edited sop_default.docx against P1/P2/P3 contexts.

Reads the edited template at /home/wesuuu/Code/trellisbio/sop_default.docx,
runs each SOP permutation through build_context + render_to_docx, writes
.docx + .pdf into tests/fixtures/template-permutations/rendered-user-edit/.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Import the live build_context + render_to_docx and the same builders the
# permutation suite uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.protocols.template_engine import build_context, render_to_docx
from tests.integration.fixtures.template_permutations import builders

USER_TEMPLATE = Path("/home/wesuuu/Code/trellisbio/sop_default.docx")
OUT_ROOT = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/template-permutations/rendered-user-edit"
)


def _convert_to_pdf(docx_path: Path) -> Path | None:
    try:
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(docx_path.parent),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as e:
        print(f"  PDF conversion failed: {e}")
        return None
    pdf_path = docx_path.with_suffix(".pdf")
    return pdf_path if pdf_path.exists() else None


def main() -> int:
    if not USER_TEMPLATE.exists():
        print(f"ERROR: edited template not found at {USER_TEMPLATE}")
        return 1
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    for builder_name in ("build_p1", "build_p2", "build_p3"):
        built = getattr(builders, builder_name)()
        if "sop" not in built.renders_against:
            continue
        print(f"\n=== {built.name} ===")
        ctx, unresolved = build_context(**built.kwargs)
        ctx.setdefault("approval", None)
        ctx.setdefault("approval_history", [])
        ctx.setdefault("unapproved_warning", "")
        if built.context_overrides:
            ctx.update(built.context_overrides)
        if unresolved:
            print(f"  WARNING: unresolved tokens: {unresolved}")

        docx_bytes = render_to_docx(str(USER_TEMPLATE), ctx)
        outdir = OUT_ROOT / built.name
        outdir.mkdir(parents=True, exist_ok=True)
        docx_path = outdir / "sop.docx"
        docx_path.write_bytes(docx_bytes)
        print(f"  wrote {docx_path} ({len(docx_bytes)} bytes)")
        pdf_path = _convert_to_pdf(docx_path)
        if pdf_path:
            print(f"  wrote {pdf_path} ({pdf_path.stat().st_size} bytes)")

    print(f"\nOutputs under: {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
