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
