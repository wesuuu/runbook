# Services Directory Domain Reorganization (TD-0079)

**Scope:** Backend refactor — no behavior changes.

## Problem

`backend/app/services/` holds 31 independent `.py` modules plus three subdirectories. The flat layout hides relationships between modules and makes it hard to understand the service surface at a glance.

## Goal

Reorganize into six feature-domain subdirectories with all imports rewritten to the new paths. No backward-compat shim.

## Target Structure

```
backend/app/services/
├── __init__.py
├── ai/
│   ├── __init__.py
│   ├── ai_config.py
│   ├── ai_provider_validation.py
│   ├── ai_vision.py
│   ├── chat_service.py
│   ├── embedding.py
│   ├── protocol_generator.py
│   └── sop_generator.py
├── documents/
│   ├── __init__.py
│   ├── document_processor.py
│   ├── document_structure.py
│   ├── export.py
│   ├── markdown_chunker.py
│   ├── pdf.py
│   ├── pdf_base.py
│   ├── fonts/            # existing DejaVu font assets
│   └── templates/        # existing .docx templates
├── protocols/
│   ├── __init__.py
│   ├── protocol_importer.py
│   ├── template_converter.py
│   ├── template_engine.py
│   ├── template_seeder.py
│   └── url_importer.py
├── batch/
│   ├── __init__.py
│   ├── batch_record_extractor.py
│   └── batch_record_generator.py
├── data/
│   ├── __init__.py
│   ├── graph_processing.py
│   └── text_chunker.py
└── core/
    ├── __init__.py
    ├── audit.py
    ├── background_jobs.py
    ├── email_service.py
    ├── file_storage.py
    ├── oauth.py
    ├── onboarding.py
    ├── permissions.py
    ├── rate_limit.py
    ├── task_runner.py
    └── notifications/    # existing package (dispatcher, channels/, templates.py)
```

`task_runner` lives in `core/` (makes core 9 modules; the task spec's "8" is close enough — infrastructure is the right home for it).

## Asset Relocations

- `services/fonts/` → `services/documents/fonts/`
- `services/templates/` → `services/documents/templates/`
- `services/notifications/` → `services/core/notifications/`

Any file_storage / pdf / batch_record_generator code that resolves template or font paths must be updated to the new relative locations.

## Import Migration

All 209 references to `from app.services.<module>` across 86 files get rewritten to `from app.services.<domain>.<module>`. No re-exports are added to `services/__init__.py`; old paths stop working intentionally.

Each new `<domain>/__init__.py` is empty (no re-exports). Consumers import specific modules.

## Non-Goals

- No renaming of modules, functions, or classes.
- No changes to service logic, signatures, or tests beyond import paths.
- No reorganization of `api/endpoints/`, `models/`, `schemas/`.

## Success Criteria

- `pytest` passes with identical counts to pre-refactor baseline.
- `mypy app` shows no new errors.
- `grep -r "from app.services\." backend/ | grep -v "app.services\.\(ai\|documents\|protocols\|batch\|data\|core\)"` returns nothing (excluding this spec).
- Dev server starts cleanly (`uvicorn app.main:app`).

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Missed import site breaks runtime | Run full test suite + `mypy`; grep assertion above |
| Path references to moved assets (fonts, templates) | Audit `Path(__file__).parent` and relative string paths in the three modules most likely affected (pdf_base, batch_record_generator, sop_generator) |
| Circular imports surface after split | If a domain `__init__.py` eagerly imports submodules, keep it empty |
| Git history lost on renames | Use `git mv` for each file so rename is tracked |
