"""F-0043 — synchronous PDF export for an experiment summary.

CPU-bound fpdf2 work. Endpoint wraps the call in asyncio.to_thread +
asyncio.wait_for so the event loop and HTTP worker stay responsive.

Unicode-safe: biotech content uses µ, °, ±, Δ, β routinely. We register
DejaVuSans (shipped under `backend/app/static/fonts/DejaVuSans*.ttf` — copy
from a system install if absent) and use it for every cell. Helvetica is
Latin-1 only and would mojibake or raise on the first µ.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

from fpdf import FPDF

from app.services.experiments.conditions import compute_conditions

_FONT_DIR = Path(__file__).resolve().parents[2] / "static" / "fonts"
_FONT_FILES = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf")

# Bounded thread pool so a burst of PDF requests can't exhaust the default
# asyncio executor (which is shared with every other to_thread caller).
# Two slots match the practical worker count and keep memory in check;
# additional callers queue without blocking the event loop.
PDF_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf-export")


def assert_fonts_available() -> None:
    """Fail fast at app startup if PDF fonts are missing.

    Without this we'd raise at the first export request, after the user
    already clicked "Export PDF" — much worse failure mode than a noisy
    boot.
    """
    missing = [f for f in _FONT_FILES if not (_FONT_DIR / f).exists()]
    if missing:
        raise RuntimeError(
            f"PDF export fonts missing in {_FONT_DIR}: {missing}. "
            "Copy DejaVuSans* from a system install (e.g. fonts-dejavu)."
        )


def _make_pdf() -> FPDF:
    pdf = FPDF()
    pdf.add_font("DejaVu", "", str(_FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(_FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.add_font("DejaVu", "I", str(_FONT_DIR / "DejaVuSans-Oblique.ttf"))
    return pdf


def _header(pdf: FPDF, experiment) -> None:
    pdf.set_font("DejaVu", "B", 16)
    pdf.cell(0, 10, f"Experiment: {experiment.name}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    # Byte-stable header: when the conclusion is locked, anchor "Exported"
    # to the lock timestamp so two consecutive exports of the same locked
    # experiment produce identical bytes (hash-based integrity, regulator
    # round-trip tests, and the dedup cache all rely on this).
    if experiment.conclusion_locked_at:
        exported = experiment.conclusion_locked_at.isoformat()
    else:
        exported = "draft"
    pdf.cell(
        0, 6,
        f"Slug: {experiment.slug}  •  Exported: {exported}",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(4)


def _objective(pdf: FPDF, experiment) -> None:
    if not experiment.objective:
        return
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Objective", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.multi_cell(0, 5, experiment.objective, new_x="LMARGIN", new_y="NEXT")
    if experiment.success_criteria:
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(0, 6, "Success criteria:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 10)
        for c in experiment.success_criteria:
            pdf.cell(0, 5, f"  • {c}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _conditions(pdf: FPDF, runs: Iterable[Any]) -> None:
    rows = compute_conditions(
        [{"id": str(r.id), "graph": r.graph or {}} for r in runs]
    )
    varied = [row for row in rows if row["varied"]]
    if not varied:
        return
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Conditions (varied parameters)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9)
    for row in varied:
        line = f"{row['nodeLabel']} / {row['paramKey']}: " + ", ".join(
            f"{rid}={c['value']}{(' ' + c['unit']) if c.get('unit') else ''}"
            for rid, c in row["perRun"].items()
        )
        pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _key_results(pdf: FPDF, runs: Iterable[Any]) -> None:
    with_kr = [r for r in runs if r.key_result_value is not None]
    if not with_kr:
        return
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Key results", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    best = max(with_kr, key=lambda r: r.key_result_value)
    for r in sorted(with_kr, key=lambda r: r.key_result_value, reverse=True):
        suffix = " (best)" if r.id == best.id else ""
        unit = f" {r.key_result_unit}" if r.key_result_unit else ""
        pdf.cell(
            0, 5,
            f"  {r.name}: {r.key_result_label} = {r.key_result_value}{unit}{suffix}",
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(4)


def _conclusion(pdf: FPDF, experiment) -> None:
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Conclusion", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    if experiment.conclusion_locked_at:
        pdf.multi_cell(0, 5, experiment.conclusion or "", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("DejaVu", "I", 9)
        signer = experiment.conclusion_locked_by_name or "system"
        pdf.cell(
            0, 5,
            f"Locked by {signer} on {experiment.conclusion_locked_at.isoformat()}",
            new_x="LMARGIN", new_y="NEXT",
        )
    else:
        pdf.set_text_color(180, 90, 0)
        pdf.cell(0, 5, "Not yet locked — draft", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        if experiment.conclusion:
            pdf.multi_cell(0, 5, experiment.conclusion, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _observations(pdf: FPDF, observations: list[dict]) -> None:
    if not observations:
        return
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Observations", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9)
    for o in observations:
        flag = (o["flag"] or "").upper()
        ts = o["created_at"]
        body = o.get("body") or ""
        run = f" ({o['run_label']})" if o.get("run_label") else ""
        pdf.multi_cell(0, 4, f"[{flag}] {ts}{run} — {body}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def generate_experiment_pdf(experiment, runs: list[Any], observations: list[dict]) -> bytes:
    """Render the experiment summary to a PDF byte string.

    Synchronous and CPU-bound — caller is responsible for asyncio.to_thread.
    """
    pdf = _make_pdf()
    pdf.add_page()
    _header(pdf, experiment)
    _objective(pdf, experiment)
    _conditions(pdf, runs)
    _key_results(pdf, runs)
    _conclusion(pdf, experiment)
    _observations(pdf, observations)
    out = pdf.output(dest="S")
    return bytes(out) if not isinstance(out, bytes) else out
