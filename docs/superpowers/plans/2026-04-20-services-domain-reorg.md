# Services Directory Domain Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize 31 modules in `backend/app/services/` into six domain subdirectories (ai/, documents/, protocols/, batch/, data/, core/) and rewrite all 209 import sites, with no behavior changes.

**Architecture:** Pure mechanical refactor. `git mv` each module under its domain, create empty `__init__.py` per domain, then rewrite `from app.services.<mod>` → `from app.services.<domain>/<mod>` across the codebase. Three asset subdirs (`fonts/`, `templates/`, `notifications/`) move with their domain. Two `Path(__file__).parent` references are adjusted explicitly.

**Tech Stack:** Python 3, FastAPI, pytest, sed for bulk rewrites, git mv to preserve history.

**Spec:** `docs/superpowers/specs/2026-04-20-services-domain-reorg-design.md`

**Working dir:** `backend/` for all backend commands. Activate venv first: `cd backend && source .venv/bin/activate`.

---

## Domain mapping (locked)

| Domain | Modules |
|---|---|
| `ai/` (7) | ai_config, ai_provider_validation, ai_vision, chat_service, embedding, protocol_generator, sop_generator |
| `documents/` (6 + fonts/ + templates/) | document_processor, document_structure, export, markdown_chunker, pdf, pdf_base |
| `protocols/` (5) | protocol_importer, template_converter, template_engine, template_seeder, url_importer |
| `batch/` (2) | batch_record_extractor, batch_record_generator |
| `data/` (2) | graph_processing, text_chunker |
| `core/` (9 + notifications/) | audit, background_jobs, email_service, file_storage, oauth, onboarding, permissions, rate_limit, task_runner |

Asset relocations:
- `services/fonts/` → `services/documents/fonts/`
- `services/templates/` → `services/documents/templates/` (.docx files)
- `services/notifications/` → `services/core/notifications/`

---

### Task 1: Capture baseline

**Files:** none (read-only).

- [ ] **Step 1: Activate venv and run full test suite, capture pass/fail counts**

```bash
cd backend && source .venv/bin/activate
pytest --tb=no -q 2>&1 | tail -5
```

Record the summary line (e.g., `200 passed, 3 skipped in 45s`). This is the post-refactor target.

- [ ] **Step 2: Capture mypy baseline**

```bash
mypy app 2>&1 | tail -3
```

Record error count. Post-refactor must be ≤ this number.

- [ ] **Step 3: Confirm import-site count**

```bash
grep -rn "from app\.services\." backend/ | wc -l
```

Expected: 209 (informational; will not all change — many already point to `app.services.notifications.*` which becomes `app.services.core.notifications.*`).

- [ ] **Step 4: Stash baseline as a comment in scratch file (do not commit)**

No commit for this task — just hold the numbers in mind for the final verification.

---

### Task 2: Create domain skeleton

**Files:**
- Create: `backend/app/services/ai/__init__.py`
- Create: `backend/app/services/documents/__init__.py`
- Create: `backend/app/services/protocols/__init__.py`
- Create: `backend/app/services/batch/__init__.py`
- Create: `backend/app/services/data/__init__.py`
- Create: `backend/app/services/core/__init__.py`

- [ ] **Step 1: Create the six empty `__init__.py` files**

```bash
cd backend
for d in ai documents protocols batch data core; do
  mkdir -p "app/services/$d"
  : > "app/services/$d/__init__.py"
done
```

- [ ] **Step 2: Verify**

```bash
ls app/services/{ai,documents,protocols,batch,data,core}/__init__.py
```

Expected: all six paths listed.

- [ ] **Step 3: Commit**

```bash
git add app/services/{ai,documents,protocols,batch,data,core}/__init__.py
git commit -m "refactor(services): scaffold domain subdirectories (TD-0079)"
```

---

### Task 3: Move `ai/` modules and rewrite imports

**Files (move with `git mv`):**
- `backend/app/services/ai_config.py` → `backend/app/services/ai/ai_config.py`
- `backend/app/services/ai_provider_validation.py` → `backend/app/services/ai/ai_provider_validation.py`
- `backend/app/services/ai_vision.py` → `backend/app/services/ai/ai_vision.py`
- `backend/app/services/chat_service.py` → `backend/app/services/ai/chat_service.py`
- `backend/app/services/embedding.py` → `backend/app/services/ai/embedding.py`
- `backend/app/services/protocol_generator.py` → `backend/app/services/ai/protocol_generator.py`
- `backend/app/services/sop_generator.py` → `backend/app/services/ai/sop_generator.py`

- [ ] **Step 1: Move files**

```bash
cd backend
for m in ai_config ai_provider_validation ai_vision chat_service embedding protocol_generator sop_generator; do
  git mv "app/services/${m}.py" "app/services/ai/${m}.py"
done
```

- [ ] **Step 2: Rewrite imports across the entire backend tree**

```bash
cd backend
for m in ai_config ai_provider_validation ai_vision chat_service embedding protocol_generator sop_generator; do
  grep -rl "app\.services\.${m}\b" --include="*.py" . \
    | xargs sed -i "s|app\.services\.${m}\b|app.services.ai.${m}|g"
done
```

- [ ] **Step 3: Verify no stale references**

```bash
grep -rn "from app\.services\.\(ai_config\|ai_provider_validation\|ai_vision\|chat_service\|embedding\|protocol_generator\|sop_generator\)\b" --include="*.py" .
grep -rn "import app\.services\.\(ai_config\|ai_provider_validation\|ai_vision\|chat_service\|embedding\|protocol_generator\|sop_generator\)\b" --include="*.py" .
```

Expected: both return nothing.

- [ ] **Step 4: Run AI-related unit tests**

```bash
pytest tests/unit/test_ai_config.py tests/unit/test_ai_vision.py tests/unit/test_chat_service.py tests/unit/test_embedding.py tests/unit/test_protocol_generator.py -v --tb=short
```

Expected: all pass (same as baseline).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(services): move ai modules to ai/ subdirectory (TD-0079)"
```

---

### Task 4: Move `documents/` modules, relocate `fonts/`, rewrite imports, fix `pdf_base` path

**Files:**
- `git mv` six modules into `documents/`
- `git mv backend/app/services/fonts` → `backend/app/services/documents/fonts`
- Edit: `backend/app/services/documents/pdf_base.py` (font import path)

- [ ] **Step 1: Move six document modules**

```bash
cd backend
for m in document_processor document_structure export markdown_chunker pdf pdf_base; do
  git mv "app/services/${m}.py" "app/services/documents/${m}.py"
done
```

- [ ] **Step 2: Move `fonts/` into `documents/`**

```bash
git mv app/services/fonts app/services/documents/fonts
```

- [ ] **Step 3: Rewrite imports for the six document modules**

```bash
for m in document_processor document_structure export markdown_chunker pdf pdf_base; do
  grep -rl "app\.services\.${m}\b" --include="*.py" . \
    | xargs sed -i "s|app\.services\.${m}\b|app.services.documents.${m}|g"
done
```

- [ ] **Step 4: Rewrite the single `app.services.fonts` reference**

```bash
grep -rl "app\.services\.fonts\b" --include="*.py" . \
  | xargs sed -i "s|app\.services\.fonts\b|app.services.documents.fonts|g"
```

Verify by checking [pdf_base.py](backend/app/services/documents/pdf_base.py) line ~15 now reads `from app.services.documents.fonts import FONTS_DIR`.

- [ ] **Step 5: Verify no stale references**

```bash
grep -rn "from app\.services\.\(document_processor\|document_structure\|export\|markdown_chunker\|pdf\|pdf_base\|fonts\)\b" --include="*.py" .
```

Expected: nothing.

- [ ] **Step 6: Run document/PDF tests**

```bash
pytest tests/unit/test_pdf_helpers.py tests/unit/test_pdf_extraction.py tests/unit/test_markdown_chunker.py tests/unit/test_sop_pdf.py -v --tb=short
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(services): move document modules and fonts to documents/ (TD-0079)"
```

---

### Task 5: Move `protocols/` modules, relocate `templates/`, fix `template_seeder` path

**Files:**
- `git mv` five modules into `protocols/`
- `git mv backend/app/services/templates` → `backend/app/services/documents/templates`
- Edit: `backend/app/services/protocols/template_seeder.py` line 13

- [ ] **Step 1: Move five protocol modules**

```bash
cd backend
for m in protocol_importer template_converter template_engine template_seeder url_importer; do
  git mv "app/services/${m}.py" "app/services/protocols/${m}.py"
done
```

- [ ] **Step 2: Move `templates/` (.docx assets) into `documents/`**

```bash
git mv app/services/templates app/services/documents/templates
```

- [ ] **Step 3: Rewrite imports**

```bash
for m in protocol_importer template_converter template_engine template_seeder url_importer; do
  grep -rl "app\.services\.${m}\b" --include="*.py" . \
    | xargs sed -i "s|app\.services\.${m}\b|app.services.protocols.${m}|g"
done
```

- [ ] **Step 4: Fix `template_seeder` path reference**

`template_seeder` previously had `SYSTEM_TEMPLATES_SOURCE = Path(__file__).parent / "templates"`. After the move, `__file__` is at `services/protocols/template_seeder.py` but the assets are at `services/documents/templates/`. Update line 13 of [template_seeder.py](backend/app/services/protocols/template_seeder.py):

```python
SYSTEM_TEMPLATES_SOURCE = Path(__file__).parent.parent / "documents" / "templates"
```

Also update the docstring on line 4 if it references `app/services/templates/` — change to `app/services/documents/templates/`.

- [ ] **Step 5: Verify path resolves**

```bash
python -c "from app.services.protocols.template_seeder import SYSTEM_TEMPLATES_SOURCE; print(SYSTEM_TEMPLATES_SOURCE); assert SYSTEM_TEMPLATES_SOURCE.exists(), 'missing templates dir'; assert (SYSTEM_TEMPLATES_SOURCE / 'sop_default.docx').exists(), 'missing sop_default.docx'"
```

Expected: prints the resolved path, no assertion errors.

- [ ] **Step 6: Run protocol tests**

```bash
pytest tests/unit/test_protocol_importer.py tests/unit/test_template_engine.py tests/unit/test_template_converter.py -v --tb=short
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(services): move protocol modules to protocols/, templates/ to documents/ (TD-0079)"
```

---

### Task 6: Move `batch/` modules

**Files:**
- `git mv backend/app/services/batch_record_extractor.py` → `backend/app/services/batch/batch_record_extractor.py`
- `git mv backend/app/services/batch_record_generator.py` → `backend/app/services/batch/batch_record_generator.py`

- [ ] **Step 1: Move files**

```bash
cd backend
git mv app/services/batch_record_extractor.py app/services/batch/batch_record_extractor.py
git mv app/services/batch_record_generator.py app/services/batch/batch_record_generator.py
```

- [ ] **Step 2: Rewrite imports**

```bash
for m in batch_record_extractor batch_record_generator; do
  grep -rl "app\.services\.${m}\b" --include="*.py" . \
    | xargs sed -i "s|app\.services\.${m}\b|app.services.batch.${m}|g"
done
```

- [ ] **Step 3: Verify**

```bash
grep -rn "from app\.services\.\(batch_record_extractor\|batch_record_generator\)\b" --include="*.py" .
```

Expected: nothing.

- [ ] **Step 4: Run batch tests**

```bash
pytest tests/unit/test_batch_record.py tests/unit/test_batch_record_extractor.py tests/integration/test_batch_record_import_api.py -v --tb=short
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(services): move batch record modules to batch/ (TD-0079)"
```

---

### Task 7: Move `data/` modules

**Files:**
- `git mv backend/app/services/graph_processing.py` → `backend/app/services/data/graph_processing.py`
- `git mv backend/app/services/text_chunker.py` → `backend/app/services/data/text_chunker.py`

- [ ] **Step 1: Move files**

```bash
cd backend
git mv app/services/graph_processing.py app/services/data/graph_processing.py
git mv app/services/text_chunker.py app/services/data/text_chunker.py
```

- [ ] **Step 2: Rewrite imports**

```bash
for m in graph_processing text_chunker; do
  grep -rl "app\.services\.${m}\b" --include="*.py" . \
    | xargs sed -i "s|app\.services\.${m}\b|app.services.data.${m}|g"
done
```

- [ ] **Step 3: Verify**

```bash
grep -rn "from app\.services\.\(graph_processing\|text_chunker\)\b" --include="*.py" .
```

Expected: nothing.

- [ ] **Step 4: Run data tests**

```bash
pytest tests/unit/test_text_chunker.py -v --tb=short
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(services): move graph/text modules to data/ (TD-0079)"
```

---

### Task 8: Move `core/` modules and `notifications/` package

**Files:**
- `git mv` nine core modules into `core/`
- `git mv backend/app/services/notifications` → `backend/app/services/core/notifications`

- [ ] **Step 1: Move nine core modules**

```bash
cd backend
for m in audit background_jobs email_service file_storage oauth onboarding permissions rate_limit task_runner; do
  git mv "app/services/${m}.py" "app/services/core/${m}.py"
done
```

- [ ] **Step 2: Move `notifications/` package**

```bash
git mv app/services/notifications app/services/core/notifications
```

- [ ] **Step 3: Rewrite imports for the nine core modules**

```bash
for m in audit background_jobs email_service file_storage oauth onboarding permissions rate_limit task_runner; do
  grep -rl "app\.services\.${m}\b" --include="*.py" . \
    | xargs sed -i "s|app\.services\.${m}\b|app.services.core.${m}|g"
done
```

- [ ] **Step 4: Rewrite imports for `notifications` package (and its submodules)**

```bash
grep -rl "app\.services\.notifications\b" --include="*.py" . \
  | xargs sed -i "s|app\.services\.notifications\b|app.services.core.notifications|g"
```

This rewrites all of:
- `from app.services.notifications import ...`
- `from app.services.notifications.dispatcher import ...`
- `from app.services.notifications.channels import ...`
- `from app.services.notifications.channels.base import ...`
- `from app.services.notifications.templates import ...`

…including the docstring example inside [notifications/__init__.py](backend/app/services/core/notifications/__init__.py).

- [ ] **Step 5: Verify no stale references**

```bash
grep -rn "from app\.services\.\(audit\|background_jobs\|email_service\|file_storage\|oauth\|onboarding\|permissions\|rate_limit\|task_runner\|notifications\)\b" --include="*.py" .
```

Expected: nothing.

- [ ] **Step 6: Run core tests**

```bash
pytest tests/unit/test_audit.py tests/unit/test_file_storage.py tests/unit/test_permissions.py tests/unit/test_email_service.py tests/unit/test_task_runner.py tests/unit/test_onboarding_service.py tests/unit/test_background_jobs.py tests/unit/test_notifications.py -v --tb=short
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(services): move core modules and notifications package to core/ (TD-0079)"
```

---

### Task 9: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Confirm flat services dir is empty of modules**

```bash
cd backend
ls app/services/
```

Expected: only `__init__.py`, `__pycache__`, and the six domain subdirectories. No stray `.py` files.

- [ ] **Step 2: Assert no stale `app.services.<oldname>` references**

```bash
grep -rEn "from app\.services\.[a-z_]+ import" --include="*.py" . \
  | grep -vE "from app\.services\.(ai|documents|protocols|batch|data|core)\." \
  || echo "OK - no stale services imports"
```

Expected: prints `OK - no stale services imports`.

- [ ] **Step 3: Run mypy**

```bash
mypy app 2>&1 | tail -5
```

Expected: error count ≤ Task 1 baseline.

- [ ] **Step 4: Run full test suite**

```bash
pytest --tb=short -q 2>&1 | tail -10
```

Expected: pass count == Task 1 baseline.

- [ ] **Step 5: Smoke-test app import**

```bash
python -c "from app.main import app; print('OK', len(app.routes), 'routes')"
```

Expected: `OK <N> routes` with no traceback.

- [ ] **Step 6: Smoke-test dev server boot (5-second timeout)**

```bash
timeout 5 uvicorn app.main:app --port 8077 2>&1 | head -20 || true
```

Expected: lines like `Application startup complete.` with no `ImportError` / `ModuleNotFoundError`.

- [ ] **Step 7: Lint**

```bash
black app tests --check && isort app tests --check-only
```

Expected: pass. If reformat needed, run `black app tests && isort app tests` and amend the last commit.

- [ ] **Step 8: Final commit (if lint changed anything)**

```bash
git add -A
git diff --cached --quiet || git commit -m "refactor(services): apply black/isort after reorg (TD-0079)"
```
