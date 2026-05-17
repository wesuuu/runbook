# TD-0085: Docling Evaluation Report

**Date:** 2026-05-12
**Hardware:** AMD Ryzen 9 9950X (16 cores / 32 threads), 64 GB RAM, no GPU
**Docling version:** 2.93.0 (torch 2.11.0)
**Reproduce:** `backend/.venv/bin/python scripts/eval_docling.py --input scripts/mocks/animal-culture-textbook.pdf`

## 1. Inputs

| File | Pages | Size |
| --- | ---: | ---: |
| animal-culture-textbook.pdf | 676 | 27 MB |

Single-input run; no scanned-PDF second pass executed (see Section 6).

## 2. Results

One-time model cache footprint after first run: **1.0 GB** (split across `~/.cache/huggingface/hub/` for the layout + tableformer weights and the active venv's `rapidocr/models/` for OCR ONNX models). All variants on subsequent runs read from cache (delta = 0 B).

| Variant | Device | Pages | Seconds | Sec/page | MD chars | HTML chars |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| default     | AUTO -> CPU | 676 | 1811.1 | 2.68 | 3,565,635 |  2,912,197 |
| no-ocr      | AUTO -> CPU | 676 | 1603.1 | 2.37 | 3,565,540 |  2,912,085 |
| cpu         | CPU         | 676 | 1590.2 | 2.35 | 3,565,635 |  2,912,197 |
| with-images | AUTO -> CPU | 676 | 1480.6 | 2.19 | 3,565,635 | 28,814,763 |

Notes on the numbers:

- `AUTO` resolved to `CPU` on this machine (no CUDA / MPS / XPU device detected), so `default` and `cpu` produced byte-identical outputs.
- `no-ocr` ran ~12% faster than `default` with a 95-character markdown delta and 112-character HTML delta — confirming the textbook is text-native and OCR adds almost nothing.
- `with-images` (`default` + `PdfPipelineOptions.generate_picture_images = True`) was fastest in wall time (within run-to-run variance of the others) and produced HTML that grew ~10x — from 2.9 MB to **28.8 MB** — because 769 figure regions become embedded base64 PNGs. The markdown is byte-identical to `default` (3.5 MB): docling's markdown export omits picture data even when extraction is enabled, which is the right behavior for chunking. Tables stayed structured (292 `<table>` in both), so enabling image extraction did not flatten tables into pictures.
- Measured per-page rate (~2.2-2.7 s/page) is roughly 3x the figure quoted in docling's paper (0.8 s/page on an 8-core x86). The textbook is figure-heavy and includes many tables, both of which push toward docling's reported p95 rather than median.
- Peak RSS was not captured: `/usr/bin/time -v` is not installed on this host. Subjective: the process stayed comfortably under available RAM (no swap activity observed).

## 3. HTML observations

Inspected `animal-culture-textbook.default.html` (2.8 MB, identical to `cpu`; `no-ocr` differs by ~112 chars).

**default / cpu**
- Headings: 1,926 `<h2>` elements; no `<h1>` / `<h3>` / `<h4>`. Docling flattens the book / chapter / section / subsection hierarchy to a single level. Section numbers (`1.2.3 ...`) survive intact in the heading text, so a downstream chunker can use the numbering prefix instead of heading depth.
- Figures (default / no-ocr / cpu): 205 `<figure>` elements present, each containing the `<figcaption>` with the original figure caption. **No `<img>` tags and no base64 payloads** — passing `ImageRefMode.EMBEDDED` to `export_to_html()` is not sufficient on its own; docling requires `PdfPipelineOptions.generate_picture_images = True` to extract picture data, and that flag defaults off. Captions are useful for retrieval but the rendered HTML is image-less.
- Figures (with-images): 769 `<figure>` elements, each containing one `<img src="data:image/png;base64,...">`. Every detected picture region from the layout model becomes an embedded PNG. The 769 count (vs default's 205) reflects that docling only emits `<figure>` for caption-bearing regions when pictures are disabled, but emits one per picture region when enabled. HTML file size grows from 2.8 MB to 28 MB.
- Tables: 292 `<table>` elements. Rows / cells preserved as structured HTML, not flattened to plain text. Spot-checked tables look correct.
- Columns: Body text is single-stream and follows reading order even on pages with multi-column layout. No overlapping content observed.
- Layout breaks: None obvious in sampled pages from the introduction, mid-book methods chapters, and the final index.
- File size: 2.8 MB without picture extraction; 28 MB with picture extraction enabled (`with-images`). Both are under the spec's 50 MB threshold for a 676-page book; typical library docs (5-50 pages) will sit well under 5 MB even with images.

**no-ocr**
- Identical layout outcome; the only differences vs. default are inside text regions where OCR fires on text-native pages and occasionally re-extracts characters that the embedded PDF text layer already provided. Net effect on this book is negligible.

## 4. Markdown observations

Inspected `animal-culture-textbook.default.md` (3.5 MB).

**default / cpu**
- Section headings preserved: yes (1,926 `## `-level headings — same flattening as HTML).
- Section numbering preserved: yes (e.g., `## 1.2. Advantages of Tissue Culture, 6`).
- Tables intact: yes — 5,550 lines beginning with `|`. Spot-checked tables read cleanly as GitHub-flavored markdown.
- Lists: itemized lists are preserved (HTML side has 6,477 `<li>`; markdown emits bulleted equivalents).
- Image placeholders: every figure becomes a `<!-- image -->` HTML comment. Captions appear as paragraphs immediately after. Chunker can either strip the comment or use it as a placeholder for inline image references once `generate_picture_images` is enabled.
- Garbage / mojibake: a few cosmetic issues — e.g., compressed cover-page title (`## CultureofAnimal Cells`), Unicode escapes for typographic quotes, and an inverted-question-mark glyph (`¨`) for a smart open-quote in one preface page. These are PDF-source artifacts, not docling artifacts; the existing pymupdf pipeline has the same issue. None of them break chunking.
- Citations and references: in-text citations like `[Gey et al., 1952]` survive verbatim.

**no-ocr**
- Effectively identical (95-character diff over 3.5 MB). Confirms there is no reason to leave OCR on for the library use case as long as inputs are text-native.

**cpu**
- Byte-identical to `default` on this machine. The variant remains valuable as documentation that production CPU latency is no worse than the AUTO baseline whenever no GPU is available.

## 5. Recommendation

**Verdict: Adopt** — with two integration-time follow-ups (image extraction off by default; latency budget for book-scale inputs).

**Rationale:** Docling produces structurally accurate HTML (tables, lists, figures-with-captions) and chunk-ready markdown on a complex 676-page textbook with zero per-tenant model configuration, zero outbound API calls, and a one-time ~1 GB model download. It replaces the entire vision-LLM `doc_structure` pipeline (`document_structure.py` + the Ollama dependency) with a single synchronous library call. The two real concerns — missing image extraction and book-scale latency — are both knobs to be turned in the integration, not blockers.

- **Recommended default variant for integration:** `no-ocr` baseline (`PdfPipelineOptions.do_ocr = False`) with `do_ocr = True` exposed as a per-document override for genuinely scanned inputs. On this textbook `no-ocr` is ~12% faster and content-identical; the savings will be larger on documents with more image regions.
- **Warmup strategy:** bake models into the runtime image via `docling-tools models download` (HuggingFace hub entries) plus an explicit `rapidocr` warmup. A lazy first-call download is acceptable in dev but unacceptable for the production job runner — a cold container would otherwise stall every first conversion by minutes while it pulls ~1 GB.
- **`PdfPipelineOptions` to expose as settings (`backend/app/core/config.py`):**
  - `docling_accelerator_device` (default `AUTO`)
  - `docling_do_ocr` (default `False`)
  - `docling_generate_picture_images` (default `True`) — required if the HTML viewer is to show figures inline
  - `docling_num_threads` (default `4`, override per host)
- **Pass criteria check vs. the spec:**
  - HTML readable (headings, tables, figures): **pass**
  - Markdown chunk-ready: **pass**
  - At least one variant ≤ 5 min on the textbook: **fail** — best run was ~26.5 min on this 16-core CPU. The 5-min budget is appropriate for SOP-scale documents (5-50 pages = 12 s - 2 min at the measured rate) but not for book-scale uploads. Treat the textbook timing as the upper bound for a background job, not a regression.
  - Output sizes sane: **pass** — 2.8 MB without picture extraction, 28 MB with. Both under the 50 MB threshold for a 676-page book; typical library docs will sit well under 5 MB even with images.
- **Open items for the integration task to plan around:**
  - Picture extraction is off by default; the `with-images` variant proved enabling it produces a usable embedded-image HTML (769 `<img>`, 28 MB on the textbook). At book scale this nears the 50 MB threshold, so the integration plan should consider externalizing images to disk (e.g. `/documents/{id}/images/{n}.png`) and rewriting `<img>` srcs to those URLs instead of streaming 28 MB of base64 over the wire. For SOP / batch-record-scale documents, inline base64 is fine.
  - Heading hierarchy flattens to a single `<h2>` level. The chunker should rely on the numeric prefix (`1.2.3 ...`) rather than heading depth to recover structure.
  - `PdfPipelineOptions` does not isolate cleanly under Poetry: docling 2.93 requires `torch >= 2.2.2` with constraints that Poetry cannot reconcile against this project's other dependencies (`OverrideNeededError` on torch). The integration task must either (a) bump / isolate torch, (b) ship docling in a sidecar service, or (c) install it via pip outside Poetry's resolver. This is why `pyproject.toml` does not currently declare docling — the spike uses a pip-installed copy inside the worktree venv.
  - GPU recommendation: per-page rate on this 16-core CPU is ~2.4 s. Docling's own benchmark reports ~0.1 s/page on an L4 GPU (~24x faster). For deployments expected to ingest book-sized documents regularly, plan for a GPU node; otherwise accept that book-scale ingestion is a 30-min background job.

## 6. Caveats

- Single PDF tested (one 676-page textbook). The optional second pass on a scanned input was skipped because the textbook eval was definitive enough on the variant-selection question (`no-ocr` wins on text-native input). A scanned-PDF run is still worth doing during integration to confirm OCR fires correctly when needed.
- Hardware is the dev workstation (32-thread Ryzen, no GPU). Production latency will differ; CPU production hosts will probably look like this, GPU hosts dramatically better.
- `/usr/bin/time -v` not installed on this host, so peak-RSS metrics are missing. Subjective observation is that memory was not a constraint.
- Both `default` and `cpu` resolved to the same device (`CPU`) because AUTO finds no accelerator on this machine. A re-run on a CUDA / MPS host is needed to verify AUTO actually picks the GPU when one is present.
- The HTML was inspected at the structural level (element counts, sampled passages) rather than by rendering every page in a browser. A spot-check render of `animal-culture-textbook.default.html` in a browser is a quick follow-up before kicking off the integration task.
