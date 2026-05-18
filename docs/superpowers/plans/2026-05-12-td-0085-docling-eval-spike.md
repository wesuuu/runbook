# TD-0085: Docling Evaluation Spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a committed eval report (`scripts/mocks/eval_report.md`) with concrete numbers and a recommendation about whether to adopt `docling` as the library document extractor, based on running it against a real 27MB textbook PDF across three configuration variants.

**Architecture:** Standalone evaluation. A single Python script (`scripts/eval_docling.py`) drives `docling.DocumentConverter` over one or more input files across three variants (`default`, `no-ocr`, `cpu`), capturing per-run metrics and writing markdown/HTML/JSON outputs. No `backend/app/` code is touched. The report is the deliverable.

**Tech Stack:** Python 3.13, Poetry venv, `docling` 2.x (already declared in `backend/pyproject.toml`), the existing main-repo virtualenv pattern from CLAUDE.md.

---

## File Structure

| Path | Purpose | Status |
| --- | --- | --- |
| `backend/.venv/` | Worktree-local Python venv | Create |
| `.gitignore` | Ignore generated/binary eval inputs | Modify |
| `scripts/mocks/` | Eval inputs (binary, gitignored) | Create |
| `scripts/mocks/animal-culture-textbook.pdf` | Symlink to main-repo copy | Create |
| `scripts/mocks/out/` | Generated md/html/json (gitignored) | Create |
| `scripts/eval_docling.py` | Eval CLI | Create |
| `scripts/mocks/eval_report.md` | Committed eval report | Create |

The CLI is one file. It does one thing: convert each (input × variant) and write outputs + a one-line summary. No abstractions beyond what's needed to iterate variants.

---

## Task 1: Worktree venv + verify docling import

**Files:**
- Create: `backend/.venv/`

- [ ] **Step 1: Create the worktree's Python venv**

The worktree was checked out without an installed `.venv`. Per `CLAUDE.md`, each worktree gets its own.

Run:
```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install poetry && poetry install --no-root
```

Expected: poetry resolves and installs all deps including `docling = "^2.0"`. First-run will pull a lot of ML transitive deps (torch, transformers, easyocr) — expect several minutes.

- [ ] **Step 2: Verify docling imports**

Run:
```bash
backend/.venv/bin/python -c "from docling.document_converter import DocumentConverter; print('docling import ok')"
```

Expected: `docling import ok`

- [ ] **Step 3: Verify accelerator options import**

Run:
```bash
backend/.venv/bin/python -c "from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions; print(list(AcceleratorDevice))"
```

Expected: a list including `AcceleratorDevice.AUTO`, `AcceleratorDevice.CPU`, etc.

- [ ] **Step 4: Verify pipeline options import**

Run:
```bash
backend/.venv/bin/python -c "from docling.datamodel.pipeline_options import PdfPipelineOptions; o = PdfPipelineOptions(); print(o.do_ocr, o.do_table_structure)"
```

Expected: prints two booleans (likely `True True`).

- [ ] **Step 5: No commit yet — `.venv` is gitignored**

`.venv/` is not tracked. Nothing to commit at this task.

---

## Task 2: gitignore + scripts/mocks layout

**Files:**
- Modify: `.gitignore`
- Create: `scripts/mocks/` directory
- Create: `scripts/mocks/out/` directory
- Create: `scripts/mocks/animal-culture-textbook.pdf` (symlink)

- [ ] **Step 1: Inspect current .gitignore for scripts patterns**

Run:
```bash
grep -n scripts .gitignore || echo "no scripts entries"
```

This tells you whether you're adding a new section or extending an existing one.

- [ ] **Step 2: Append the mocks ignore rule**

Add this block to the end of `.gitignore`:

```
# TD-0085 docling eval — binary inputs and generated outputs
scripts/mocks/*
!scripts/mocks/eval_report.md
!scripts/mocks/.gitkeep
```

The `!` lines whitelist the committed report and a placeholder so `scripts/mocks/` survives in git even when empty for new clones.

- [ ] **Step 3: Create the mocks directory and a .gitkeep placeholder**

Run:
```bash
mkdir -p scripts/mocks/out
touch scripts/mocks/.gitkeep
```

- [ ] **Step 4: Symlink the textbook from the main repo**

Run:
```bash
ln -s /home/wesuuu/Code/trellisbio/scripts/mocks/animal-culture-textbook.pdf scripts/mocks/animal-culture-textbook.pdf
```

- [ ] **Step 5: Verify symlink works and file is readable**

Run:
```bash
ls -lah scripts/mocks/animal-culture-textbook.pdf && file scripts/mocks/animal-culture-textbook.pdf
```

Expected: symlink resolves; `file` reports `PDF document`.

- [ ] **Step 6: Verify gitignore is correct**

Run:
```bash
git check-ignore -v scripts/mocks/animal-culture-textbook.pdf
git check-ignore -v scripts/mocks/eval_report.md && echo "WRONG — report should NOT be ignored" || echo "ok — report is tracked"
```

Expected: the PDF is ignored; the report path is NOT ignored.

- [ ] **Step 7: Commit**

```bash
git add .gitignore scripts/mocks/.gitkeep
git commit -m "$(cat <<'EOF'
chore(td-0085): scaffold scripts/mocks/ for docling eval inputs

gitignore scripts/mocks/* except eval_report.md so binary PDFs and
generated outputs don't get tracked while the eval report does.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Eval CLI skeleton (argparse, variant enum, --help)

**Files:**
- Create: `scripts/eval_docling.py`

- [ ] **Step 1: Write the CLI skeleton**

Create `scripts/eval_docling.py`:

```python
"""Evaluate docling document conversion across configuration variants.

For each input file × variant, runs DocumentConverter().convert(),
times it, and writes <basename>.<variant>.{md,html,json} to the output
directory plus a one-line summary to stdout.

Used to validate whether docling is suitable for the library extraction
pipeline (TD-0085).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

VARIANTS = ("default", "no-ocr", "cpu")


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
            f"Variant to run. Repeatable. Defaults to all: {', '.join(VARIANTS)}"
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

    print(f"inputs={len(args.input)} variants={variants} out_dir={args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify --help works**

Run:
```bash
backend/.venv/bin/python scripts/eval_docling.py --help
```

Expected: prints the docstring + argument list; exits 0.

- [ ] **Step 3: Verify it complains about missing --input**

Run:
```bash
backend/.venv/bin/python scripts/eval_docling.py
```

Expected: argparse error mentioning `--input`; exits 2.

- [ ] **Step 4: Verify it complains about missing input file**

Run:
```bash
backend/.venv/bin/python scripts/eval_docling.py --input /tmp/does-not-exist.pdf
```

Expected: stderr contains `ERROR: input not found`; exits 1.

- [ ] **Step 5: Verify the happy-path skeleton prints the inputs**

Run:
```bash
backend/.venv/bin/python scripts/eval_docling.py --input scripts/mocks/animal-culture-textbook.pdf
```

Expected: prints `inputs=1 variants=['default', 'no-ocr', 'cpu'] out_dir=scripts/mocks/out`; exits 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/eval_docling.py
git commit -m "$(cat <<'EOF'
feat(td-0085): scaffold docling eval CLI

argparse skeleton with --input (repeatable), --variant (repeatable),
--out-dir. Validates inputs exist; defaults to running all three variants.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Variant → DocumentConverter factory

**Files:**
- Modify: `scripts/eval_docling.py`

- [ ] **Step 1: Add the converter-factory function**

Insert below the `VARIANTS` constant in `scripts/eval_docling.py`:

```python
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def build_converter(variant: str) -> DocumentConverter:
    """Construct a DocumentConverter wired for the given variant.

    - default: AUTO accelerator, OCR on (baseline)
    - no-ocr:  AUTO accelerator, OCR off (text-native PDFs)
    - cpu:     forced CPU, OCR on (worst-case for no-GPU containers)
    """
    if variant == "default":
        device = AcceleratorDevice.AUTO
        do_ocr = True
    elif variant == "no-ocr":
        device = AcceleratorDevice.AUTO
        do_ocr = False
    elif variant == "cpu":
        device = AcceleratorDevice.CPU
        do_ocr = True
    else:
        raise ValueError(f"unknown variant: {variant}")

    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = do_ocr
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=4, device=device
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
        }
    )
```

- [ ] **Step 2: Verify all three variants construct without error**

Run:
```bash
backend/.venv/bin/python -c "
from scripts.eval_docling import build_converter, VARIANTS
for v in VARIANTS:
    c = build_converter(v)
    print(v, '->', type(c).__name__)
"
```

Expected: three lines, each ending in `-> DocumentConverter`. May take a few seconds (docling lazy-loads).

If the import fails with `ModuleNotFoundError: No module named 'scripts'`, use this instead:

```bash
backend/.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from eval_docling import build_converter, VARIANTS
for v in VARIANTS:
    c = build_converter(v)
    print(v, '->', type(c).__name__)
"
```

- [ ] **Step 3: Verify unknown variant raises**

Run:
```bash
backend/.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from eval_docling import build_converter
try:
    build_converter('nonsense')
except ValueError as e:
    print('ok:', e)
"
```

Expected: `ok: unknown variant: nonsense`

- [ ] **Step 4: Commit**

```bash
git add scripts/eval_docling.py
git commit -m "$(cat <<'EOF'
feat(td-0085): build_converter factory for three eval variants

default (AUTO + OCR), no-ocr (AUTO, do_ocr=False), cpu (forced CPU + OCR).
Each variant configures AcceleratorOptions + PdfPipelineOptions and
returns a fully wired DocumentConverter.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Conversion loop with output emission

**Files:**
- Modify: `scripts/eval_docling.py`

- [ ] **Step 1: Add the run_one + write_outputs helpers**

Insert below `build_converter` in `scripts/eval_docling.py`:

```python
import json
import time
from dataclasses import dataclass

from docling_core.types.doc import ImageRefMode


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

    Returns a RunResult with metrics; raises on conversion failure so
    a bad run can't be silently confused with a good one.
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
```

- [ ] **Step 2: Wire the loop into `main`**

Replace the existing body of `main` (after `args.out_dir.mkdir(...)`) with:

```python
    print(f"inputs={len(args.input)} variants={variants} out_dir={args.out_dir}")

    results: list[RunResult] = []
    for input_path in args.input:
        for variant in variants:
            print(f"-> {input_path.name} [{variant}] ...", flush=True)
            result = run_one(input_path, variant, args.out_dir)
            results.append(result)
            per_page = result.seconds / result.pages if result.pages else 0.0
            print(
                f"   {result.variant:8s} pages={result.pages:4d} "
                f"seconds={result.seconds:7.1f} sec/page={per_page:5.2f} "
                f"md_chars={result.md_chars:7d} html_chars={result.html_chars:9d} "
                f"device={result.device}",
                flush=True,
            )

    return 0
```

- [ ] **Step 3: Smoke test with the smallest available PDF**

Use one of the existing test artifacts first — way faster than the textbook for catching bugs in the script:

```bash
backend/.venv/bin/python scripts/eval_docling.py \
  --input backend/tests/artifacts/templates/sop_simple.pdf \
  --variant default
```

Expected: one summary line; three files appear in `scripts/mocks/out/sop_simple.default.{md,html,json}`. On first run, docling will lazily download models (one-time, several hundred MB). This will take a while; that's expected.

If the file paths above fail, use any PDF you can find — the point is to exercise the script end-to-end before pointing it at the 27MB textbook.

- [ ] **Step 4: Open the generated HTML to sanity-check it**

Run:
```bash
ls -lah scripts/mocks/out/sop_simple.default.*
xdg-open scripts/mocks/out/sop_simple.default.html 2>/dev/null || \
  echo "Open scripts/mocks/out/sop_simple.default.html in your browser manually"
```

Expected: the HTML renders with the SOP's headings and any tables visible.

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_docling.py
git commit -m "$(cat <<'EOF'
feat(td-0085): run_one converts one variant and writes md/html/json

Threads a RunResult dataclass through the main loop. HTML is exported
with ImageRefMode.EMBEDDED so the file is self-contained. Each line
of stdout summarizes one run: pages, seconds, sec/page, char counts,
device used.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Model cache snapshot (first-run delta)

**Files:**
- Modify: `scripts/eval_docling.py`

- [ ] **Step 1: Add the cache-size helper**

Insert near the top of `scripts/eval_docling.py` (after the other imports):

```python
def cache_dir_bytes() -> int:
    """Return the total size of ~/.cache/docling/models in bytes (0 if absent)."""
    cache = Path.home() / ".cache" / "docling" / "models"
    if not cache.exists():
        return 0
    total = 0
    for p in cache.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"
```

- [ ] **Step 2: Snapshot before and after in `main`**

In `main`, add this right after `args.out_dir.mkdir(...)`:

```python
    cache_before = cache_dir_bytes()
    print(f"cache_before={format_bytes(cache_before)}")
```

…and just before the final `return 0`:

```python
    cache_after = cache_dir_bytes()
    delta = cache_after - cache_before
    print(
        f"cache_after={format_bytes(cache_after)} "
        f"delta={format_bytes(delta)}"
    )
```

- [ ] **Step 3: Smoke-run again to confirm the cache lines print**

If the cache is already populated from Task 5's smoke test, the delta will be near zero — that's expected; it proves the snapshot logic works.

```bash
backend/.venv/bin/python scripts/eval_docling.py \
  --input backend/tests/artifacts/templates/sop_simple.pdf \
  --variant default
```

Expected: stdout begins with `cache_before=...` and ends with `cache_after=... delta=...`.

- [ ] **Step 4: Commit**

```bash
git add scripts/eval_docling.py
git commit -m "$(cat <<'EOF'
feat(td-0085): snapshot docling model cache size before/after

Captures first-run download size for the eval report. On subsequent
runs the delta will be ~0 (models cached), which is itself useful data.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Run the eval on the textbook

**Files:**
- No code changes. This task runs the script and produces artifacts under `scripts/mocks/out/`.

- [ ] **Step 1: Run all three variants on the textbook with timing**

Run (this can take a long time — the textbook is 27MB and the `cpu` variant may need 5–10 minutes):

```bash
/usr/bin/time -v backend/.venv/bin/python scripts/eval_docling.py \
  --input scripts/mocks/animal-culture-textbook.pdf \
  2>&1 | tee scripts/mocks/out/eval-run.log
```

Expected: three summary lines (one per variant), each ending with a device label. The cache before/after lines bookend the output. The `time -v` block at the end shows peak RSS and wall time.

If `/usr/bin/time -v` isn't available (e.g. macOS), use plain `time` and skip the peak-memory metric:

```bash
time backend/.venv/bin/python scripts/eval_docling.py \
  --input scripts/mocks/animal-culture-textbook.pdf \
  2>&1 | tee scripts/mocks/out/eval-run.log
```

- [ ] **Step 2: Verify the three sets of outputs exist**

Run:
```bash
ls -lah scripts/mocks/out/animal-culture-textbook.*
```

Expected: nine files — `{md,html,json}` × `{default, no-ocr, cpu}`. Note the HTML file sizes.

- [ ] **Step 3: Don't commit any of the generated files**

They're gitignored by Task 2. Confirm:

```bash
git status scripts/mocks/out/ && echo "---" && git check-ignore -v scripts/mocks/out/animal-culture-textbook.default.html
```

Expected: `git status` shows nothing under `scripts/mocks/out/`; `git check-ignore` confirms the file is ignored.

---

## Task 8: Manually inspect the outputs

**Files:**
- No code changes. This is the human-judgment step the spec hinges on.

- [ ] **Step 1: Open each variant's HTML in a browser**

Run:
```bash
for v in default no-ocr cpu; do
  echo "=== animal-culture-textbook.$v.html ==="
  ls -lah scripts/mocks/out/animal-culture-textbook.$v.html
done
echo
echo "Open each in a browser:"
echo "  file://$(pwd)/scripts/mocks/out/animal-culture-textbook.default.html"
echo "  file://$(pwd)/scripts/mocks/out/animal-culture-textbook.no-ocr.html"
echo "  file://$(pwd)/scripts/mocks/out/animal-culture-textbook.cpu.html"
```

- [ ] **Step 2: Inspect each HTML for the criteria from the spec**

For each variant, check by eye and write down what you find (you'll use this for the report in Task 9):

1. **Headings**: are section titles rendered with proper hierarchy?
2. **Figures**: are they present and visible (not broken refs)?
3. **Tables**: structured (real `<table>` markup) or flattened to plain text?
4. **Columns**: multi-column pages handled?
5. **Layout breaks**: any pages where text overlaps, runs off the edge, or is reordered nonsensically?
6. **File size**: from `ls -lah`, is each HTML under ~50MB? Where's the no-ocr vs default gap?

- [ ] **Step 3: Skim each variant's markdown**

Run:
```bash
for v in default no-ocr cpu; do
  echo "=== animal-culture-textbook.$v.md (first 200 lines) ==="
  head -200 scripts/mocks/out/animal-culture-textbook.$v.md
  echo
done
```

Check for: section headings preserved with correct levels (`#`, `##`), table rows intact (`|`-separated), no obvious garbage (mojibake, repeated text, page numbers leaking into prose), code/equation handling.

Optional deeper read: sample 3–5 random offsets across each `.md` file with `sed -n '500,600p' …` etc.

- [ ] **Step 4: Pull the per-variant numbers from `eval-run.log`**

Run:
```bash
cat scripts/mocks/out/eval-run.log
```

Note down per variant: `pages`, `seconds`, `sec/page`, `md_chars`, `html_chars`, `device`. Also note the cache `delta` (one-time download size) and peak RSS from `time -v`.

---

## Task 9: Write `scripts/mocks/eval_report.md`

**Files:**
- Create: `scripts/mocks/eval_report.md`

- [ ] **Step 1: Write the report**

Create `scripts/mocks/eval_report.md` with these exact section headings — the spec's Verification step requires all six:

````markdown
# TD-0085: Docling Evaluation Report

**Date:** YYYY-MM-DD
**Hardware:** <CPU model + core count + RAM; "no GPU" or GPU name>
**Docling version:** <run `backend/.venv/bin/python -c "from importlib.metadata import version; print(version('docling'))"`>
**Reproduce:** `backend/.venv/bin/python scripts/eval_docling.py --input scripts/mocks/animal-culture-textbook.pdf`

## 1. Inputs

| File | Pages | Size |
| --- | ---: | ---: |
| animal-culture-textbook.pdf | <N> | 27MB |

(If a second pass was run on a scanned PDF, add a row.)

## 2. Results

One-time model download: **<delta from cache snapshot>**

| Variant | Device | Pages | Seconds | Sec/page | MD chars | HTML chars |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| default | <device> | <n> | <s> | <s/p> | <n> | <n> |
| no-ocr  | <device> | <n> | <s> | <s/p> | <n> | <n> |
| cpu     | <device> | <n> | <s> | <s/p> | <n> | <n> |

Peak RSS (from `/usr/bin/time -v`): **<value>**

## 3. HTML observations

**default**
- Headings: <pass/fail + note>
- Figures: <pass/fail + note>
- Tables: <structured / flattened / mixed>
- Columns: <handled / broken / N/A>
- Layout breaks: <any specific pages or "none observed">
- File size: <X MB>

**no-ocr**
- (same shape)

**cpu**
- (same shape)

Screenshots (optional but useful): paste 2-3 PNGs into the report by drag-and-drop and reference them inline.

## 4. Markdown observations

**default**
- Section headings preserved: <yes/no>
- Tables intact: <yes/no>
- Garbage / mojibake: <none / examples>
- Notes:

**no-ocr**
- (same shape; explicitly call out any difference from default — typically only matters on scanned pages)

**cpu**
- (typically identical to default; just confirm)

## 5. Recommendation

**Verdict:** Adopt | Tune | Reject

**Rationale:** <2–4 sentences explaining the call>

If **Adopt**:
- Recommended default variant for integration: <default | no-ocr | other>
- Warmup strategy: <lazy first-call download | bake into image via `docling-tools models download` at build time | startup-warm in main.py lifespan>
- `PdfPipelineOptions` to expose as settings:
  - `docling_accelerator_device` (default `AUTO`)
  - `docling_do_ocr` (default `<true|false>`)
  - <any other knob the eval surfaced>
- Open follow-up items the integration task needs to plan around:

If **Tune**:
- What to try next (e.g. `TableFormerMode.ACCURATE`, different OCR engine, larger num_threads)
- Re-run before deciding

If **Reject**:
- Specific failure mode
- Alternatives to evaluate next (datalab/marker — GPLv3; unstructured.io — Apache-2.0; mistral-ocr)

## 6. Caveats

- Single PDF tested (textbook only); generalization to scanned SOPs / batch records is unverified beyond the optional second pass.
- Hardware is the dev machine; production latency will differ.
- <any other gotchas surfaced during the run>
````

Fill in every angle-bracketed placeholder with real data from the logs and your inspection notes. Do not leave any `<...>` token in the committed file.

- [ ] **Step 2: Verify the report has no placeholders**

Run:
```bash
grep -nE '<[A-Za-z][^>]*>' scripts/mocks/eval_report.md || echo "no placeholders"
```

Expected: `no placeholders`. (HTML tags like `<table>` won't match the regex above because they're inside fenced code; if you used any, double-check by eye.)

- [ ] **Step 3: Verify the report has all six required sections**

Run:
```bash
grep -E '^## ' scripts/mocks/eval_report.md
```

Expected: six lines — `## 1. Inputs`, `## 2. Results`, `## 3. HTML observations`, `## 4. Markdown observations`, `## 5. Recommendation`, `## 6. Caveats`.

- [ ] **Step 4: Commit the report**

```bash
git add scripts/mocks/eval_report.md
git commit -m "$(cat <<'EOF'
docs(td-0085): docling eval report

Numbers + observations + recommendation for adopting docling as the
library extractor. Reproducible via scripts/eval_docling.py.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Optional — second pass on a scanned PDF

**Files:**
- Modify: `scripts/mocks/eval_report.md` (add row + observations if pass is run)

Only run this task if Task 9's recommendation was **Adopt** or **Tune**. The point is to confirm OCR actually fires and produces usable text on a non-text-native input.

- [ ] **Step 1: Pick or create a scanned PDF**

Easiest: scan a printed page yourself, or pick one of the existing fixtures that is image-heavy. Check the existing fixtures:

```bash
for f in backend/tests/artifacts/templates/*.pdf; do
  echo "=== $f ==="
  pdftotext -nopgbrk "$f" - 2>/dev/null | wc -w
done
```

A fixture with very low word count for its page count is likely image-based.

If none qualifies, drop a scanned PDF into `/home/wesuuu/Code/trellisbio/scripts/mocks/` and symlink it the same way the textbook was.

- [ ] **Step 2: Run default and no-ocr on it**

```bash
backend/.venv/bin/python scripts/eval_docling.py \
  --input scripts/mocks/<scanned-file>.pdf \
  --variant default --variant no-ocr
```

- [ ] **Step 3: Compare**

Open the two HTML outputs. The `no-ocr` version should be largely empty for an image-only PDF; the `default` version should have OCR'd text. If `default` is also empty, that's a finding — call it out in the report.

- [ ] **Step 4: Update the report**

Add a row to the Inputs table and a fourth observation block to sections 3 + 4 (HTML / Markdown observations). If the OCR result disqualifies docling for scanned inputs, downgrade Section 5's recommendation accordingly.

- [ ] **Step 5: Commit the update**

```bash
git add scripts/mocks/eval_report.md
git commit -m "$(cat <<'EOF'
docs(td-0085): add scanned-PDF second pass to docling eval report

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Final handoff

- [ ] **Step 1: Confirm worktree state is clean**

```bash
git status
```

Expected: working tree clean.

- [ ] **Step 2: Show the user the report path + commit log**

```bash
echo "Report: $(pwd)/scripts/mocks/eval_report.md"
git log --oneline -10
```

- [ ] **Step 3: Surface the recommendation**

Quote Section 5 of the report verbatim back to the user. If the verdict is **Adopt**, remind them that the next step is creating the follow-up ClickUp task (tracked locally as task #25) once the ClickUp MCP reconnects. If **Tune**, identify what to try next. If **Reject**, name the alternative to evaluate.

---

## Spec coverage check

- ✅ Install docling (Task 1 — already declared in pyproject)
- ✅ gitignore + scripts/mocks/ layout + symlink (Task 2)
- ✅ Eval CLI with three variants (Tasks 3–6)
- ✅ Run on textbook capturing metrics (Task 7)
- ✅ Manual HTML + markdown inspection (Task 8)
- ✅ Committed `eval_report.md` with all six required sections (Task 9)
- ✅ Optional scanned-PDF second pass (Task 10)
- ✅ Verification steps 1–5 from spec mapped: script runs (Task 7 Step 1), HTML renders (Task 8 Step 1), report exists + sections (Task 9 Steps 2–3), user sign-off + follow-up task (Task 11)
- ✅ Non-goals respected — no `backend/app/`, no frontend, no migration
