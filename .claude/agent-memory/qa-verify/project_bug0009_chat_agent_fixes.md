---
name: bug0009-chat-agent-fixes
description: QA notes for BUG-0009: protocol canonical URLs, protocols.io copy, image pipeline fix
metadata:
  type: project
---

BUG-0009 has three sub-issues verified on 2026-05-22.

**Why:** Chat agent was emitting legacy `/protocols/<uuid>` links, only advertising OpenWetWare for external sources, and PNG/JPG uploads were failing with bare "[Errno 2]" from EasyOCR missing model cache.

**Sub-issue #1 — Protocol canonical URL:**
- `sanitize.py` strips `](/protocols/<anything>)` correctly; canonical `/<org>/protocols/<slug>` passes through.
- `create_protocol` tool in `shared/protocols/tools.py` calls `disambiguated_org_slug_for_user` and returns `protocol_markdown_link` as a pre-formatted `[name](/<org>/protocols/<slug>)` string.
- `protocol_creator/prompt.md` instructs the model to emit `protocol_markdown_link` verbatim, never construct its own URL.
- Unit tests for sanitizer and org-slug disambiguation: 34 pass.

**Sub-issue #2 — protocols.io copy:**
- `chat_agent.py` has `render_chat_agent_prompt(external_master_enabled, openwetware_enabled, protocols_io_enabled)` that substitutes `{{external_protocols_*}}` placeholders.
- When both sources enabled, `_source_names()` returns "OpenWetWare and protocols.io".
- `new-protocol/SKILL.md` explicitly names both sources in the picker options and dispatch rules.
- Default config has `external_protocols.enabled = True` (flipped 2026-05-24); per-source defaults are `openwetware: true`, `protocols_io: false` (needs token). Disabled-gate errors surface to chat as a generic "not available right now" message; the specific env-var lives in `logger.warning`, not the user-facing string.

**Sub-issue #4 — Image pipeline:**
- `pipeline.py` registers `InputFormat.IMAGE` with `do_ocr = True` and `EasyOcrOptions(lang=["en"], force_full_page_ocr=True)` — image uploads now extract text via EasyOCR. Originally landed with `do_ocr=False` to avoid an Errno 2 from a missing model cache; flipped on 2026-05-24 after confirming the EasyOCR model cache (`~/.EasyOCR/model/craft_mlt_25k.pth` + `english_g2.pth`) is present on the host.
- `pipeline.py` also wraps `converter.convert()` `FileNotFoundError` with `"docling could not open required file: <path>"`.
- `extract_job.py` raises the 64KB stderr cap (`_MAX_STDERR_BYTES`).
- Dev env limitation: docling-extractor `.venv` not installed (untracked), so the subprocess binary itself is missing — this surfaces as the same "[Errno 2]" at `asyncio.create_subprocess_exec` level, before any pipeline code runs. This is NOT the bug BUG-0009 targeted (which was EasyOCR cache inside the subprocess). Unit tests for `extract_job.py` and the pipeline wrapper all pass.

**How to apply:** When re-verifying sub-issue #4, ensure (a) the docling extractor `.venv` is installed at `ext/docling-extractor/.venv/bin/python` (run `cd ext/docling-extractor && poetry install` with a docling-compatible Python), and (b) the EasyOCR model cache is present on the host. Without (a) image uploads fail with "[Errno 2]" at subprocess spawn; without (b) they fail with an EasyOCR model-load error inside the subprocess.

**Library image upload API:** POST `/library/documents` requires both `file` (multipart) and `title` (form field) — the `title` field is mandatory.

**Protocols list API:** No flat `/protocols?limit=N` endpoint — protocols are project-scoped. Use project ID to filter, or `GET /protocols/by-slug/<slug>` for a specific one.
