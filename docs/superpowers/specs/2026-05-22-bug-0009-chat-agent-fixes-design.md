# BUG-0009 — Chat agent fixes (protocol link, source list, image extraction)

**Date**: 2026-05-22
**Task**: [BUG-0009] Chat agent: protocol links, sources, attachments, extraction bug
**Scope**: Sub-issues #1, #2, #4 only. Sub-issue #3 (chat attachment uploads) is split to [F-0096].

## Background

BUG-0009 bundles four chat-agent issues. Sub-issue #3 is a new capability, not a bug, so it was carved out as F-0096. This spec covers the three actual bugs.

The design was reviewed by `adversarial-risk-auditor` and `dry-reuse-auditor` before implementation; the items below incorporate their HIGH/MED findings.

## Sub-issue #1 — Wrong protocol link in chat agent

### Cause

`backend/app/services/ai/subagents/protocol_creator/prompt.md:200-203` instructs the model to emit `[Protocol Name](/protocols/<protocol_id>)`. Two things are wrong: it uses the protocol id instead of the slug, and it omits the org segment. The canonical SvelteKit route (F-0091) is `/{org_slug}/protocols/{slug}`.

`backend/app/services/core/notifications/links.py` already constructs the canonical URL correctly for notification deep links, including the disambiguation rule that mirrors the frontend's `disambiguatedOrgSlug` (collisions get an id-prefix suffix). Its helper is private to the module.

Two layered failure modes in the existing design:

1. **The prompt's URL template is wrong.** A `protocol_url` in the tool result fixes the data path.
2. **Even with a correct URL field, the model can still hallucinate a path.** "Don't construct the URL yourself" in the prompt is necessary but insufficient — LLMs ignore negative instructions under pressure. We need a server-side sanitizer as a backstop.

### Fix

1. **New shared helper module** `backend/app/services/core/org_slugs.py` exposing two public functions:

   ```python
   def disambiguate_org_slugs(
       orgs: Sequence[tuple[UUID, str]],
   ) -> dict[UUID, str]:
       """Map org id -> URL slug. Call this when you already hold the
       membership rows; prefer ``disambiguated_org_slug_for_user`` otherwise.
       Slugs that are empty or hyphen-leading after slugification are
       returned as empty strings so callers can degrade to None."""

   async def disambiguated_org_slug_for_user(
       db: AsyncSession, user_id: UUID, org_id: UUID
   ) -> str | None:
       """Resolve the URL slug for ``org_id`` in the context of ``user_id``'s
       org memberships, applying the same disambiguation rule as the frontend
       ``disambiguatedOrgSlug``. Returns None if the user is not a member of
       the org or if the resolved slug is blank/hyphen-leading."""
   ```

   `disambiguated_org_slug_for_user` loads the user's memberships in one query, calls `disambiguate_org_slugs`, applies the blank-slug guard, and returns the slug for `org_id` or `None`.

   Reuse-auditor note: keeping the batch form public (not underscore-prefixed) so `links.py` can call it cleanly without reaching into a sibling module's internals.

2. **Refactor `links.py`** to delete `_disambiguated_org_slugs` and import `disambiguate_org_slugs` from `org_slugs.py`. The blank-slug guard at `links.py:160-165` stays (it's per-route, not per-helper).

3. **Add `protocol_url` and `protocol_markdown_link` to `CreateProtocolResult`** in `backend/app/services/ai/subagents/shared/protocols/tools.py:120`. Declare both with `None` defaults:

   ```python
   @dataclass
   class CreateProtocolResult:
       ...
       protocol_url: str | None = None
       protocol_markdown_link: str | None = None
   ```

   In `create_protocol`, after the service call:

   ```python
   org_slug = await disambiguated_org_slug_for_user(
       ctx.deps.db, ctx.deps.user_id, ctx.deps.org_id
   )
   protocol_url = (
       f"/{org_slug}/protocols/{protocol.slug}" if org_slug else None
   )
   protocol_markdown_link = (
       f"[{protocol.name}]({protocol_url})" if protocol_url else None
   )
   ```

   Pre-formatting the markdown link server-side is the durable fix: even if the model ignores the link instructions, the worst it can do is paraphrase the name — it can't invent the URL.

4. **Update `protocol_creator/prompt.md` "End of turn" section** to:
   - Drop the legacy `/protocols/<protocol_id>` template entirely.
   - Instruct the model: "Emit `protocol_markdown_link` from the `create_protocol` result verbatim. If `protocol_markdown_link` is `None`, mention the protocol name as plain text and note that the link could not be resolved."
   - The prompt MUST NOT show any example of constructing a `/protocols/...` URL by hand.

5. **Add an LLM-output sanitizer** in the chat pipeline. Add a helper to `backend/app/services/ai/output_sanitizer.py` (new module) exposing:

   ```python
   _BARE_PROTOCOL_LINK = re.compile(r"\]\(/protocols/[^)]+\)")

   def strip_bare_protocol_links(text: str) -> str:
       """Strip `(/protocols/...)` from any markdown link the model emits
       outside the canonical `/{org_slug}/protocols/{slug}` form. Leaves the
       `[label]` text so the user still sees the protocol name."""
   ```

   Call it from `send_message.py` on the final assistant text before persistence. The regex matches `](/protocols/...)` only — it leaves `](/{org-slug}/protocols/...)` alone because that starts with `/{org}` not `/protocols`. This is a belt-and-braces backstop, not the primary fix.

### Known limitation (accepted)

`protocol_url` is computed at tool-call time. If the org is renamed afterward, the markdown link in the chat history becomes stale (404 → SvelteKit shows a not-found page). Same caveat applies to notification deep links and is out of scope for this fix; logged as a follow-up only if support reports it.

### Tests

- **Unit** `backend/tests/unit/test_org_slugs.py`:
  - User in one org → returns slugified org name.
  - User in two orgs whose names collide → both get `-{prefix}` suffix.
  - User not a member of `org_id` → returns `None`.
  - Org name with no alphanumeric content (e.g., `"---"`, `"!!!"`) → returns `None` (boundary for the blank-slug guard).
  - `disambiguate_org_slugs` directly: empty input, single org, colliding pair, no-alphanumeric name.
- **Unit** `backend/tests/unit/test_notification_links.py` — existing tests must still pass post-refactor; no test changes expected.
- **Unit** `backend/tests/unit/test_protocol_creator_tools.py` (new) — `create_protocol` returns:
  - `protocol_url` of the form `/{org-slug}/protocols/{slug}`.
  - `protocol_markdown_link` equal to `[<name>](<protocol_url>)`.
  - Both `None` when the user is not a member of the target org (defensive — shouldn't happen in practice).
  - Does NOT re-test the slug collision algorithm (covered in `test_org_slugs.py`).
- **Unit** `backend/tests/unit/test_output_sanitizer.py` (new):
  - Bare `[Name](/protocols/<uuid>)` → stripped to `[Name]`.
  - Canonical `[Name](/acme/protocols/my-slug)` → unchanged.
  - Multiple links in one message handled.
  - Non-protocol links (e.g., `[X](/projects/...)`) untouched.
- **Prompt assertion** in `backend/tests/unit/test_protocol_creator_prompt.py` (new) — `protocol_creator/prompt.md`:
  - Does NOT contain the literal substring `/protocols/<protocol_id>`.
  - Does reference `protocol_markdown_link`.
- **Integration** `backend/tests/integration/test_chat_protocol_link.py` (new) — drive `send_message` end-to-end with a stubbed model that triggers `create_protocol`; assert the persisted assistant message contains the canonical URL form and contains no bare `/protocols/<uuid>` substring. This is the only test that exercises sanitizer + tool-result wiring together.

## Sub-issue #2 — protocols.io not advertised by parent chat agent

### Cause

The `protocol_knowledgebase` subagent itself correctly supports OpenWetWare and protocols.io (see `subagents/protocol_knowledgebase/prompt.md`, `config.py`, and `tools.py`). The bug is in the parent surfaces that advertise the subagent:

- `backend/app/services/ai/prompts/chat_agent.md:9` describes the subagent as "search OpenWetWare for…" — singular source.
- `chat_agent.md` section "External protocols (OpenWetWare)" never mentions protocols.io.
- `backend/app/services/ai/skills/new-protocol/SKILL.md` lists "OpenWetWare" as the external-source route, not "OpenWetWare and protocols.io".

End result: when a user asks "what sources can you derive protocols from?", the parent answers OpenWetWare only, because that's all its system prompt names.

### Important: per-source feature flags

`features.external_protocols.openwetware.enabled` and `features.external_protocols.protocols_io.enabled` are independent. Naively hardcoding both into the prompt would have the agent advertise protocols.io even when its flag is off — promising capability the backend will reject.

The fix must therefore parameterize the prompt at agent build time based on which sources are actually enabled.

### Fix

1. **Render the chat-agent system prompt at build time**, not as a static file.
   - Convert `chat_agent.md` to a template that contains placeholders for the external-protocols section, e.g. `{{external_protocols_section}}` and `{{external_protocols_one_liner}}`.
   - In `backend/app/services/ai/chat_agent.py` (where the system prompt is loaded), inspect `settings.features.external_protocols` and substitute:
     - Both sources enabled → "OpenWetWare and protocols.io".
     - Only OpenWetWare → "OpenWetWare" (current behavior).
     - Only protocols.io → "protocols.io".
     - Master flag off (or neither sub-source enabled) → drop the external-protocols section + drop the subagent one-liner entirely.
   - Use simple `str.replace` substitution; introducing Jinja for two placeholders is over-engineering.

2. **Subagent returns `source_label`**. In `subagents/protocol_knowledgebase/tools.py`, the result type for the public search/fetch tool gains `source_label: str` populated with `"OpenWetWare"` or `"protocols.io"` based on the connector that produced the hit. The parent agent uses this verbatim in its `[<source_label> source](<url>)` citation — eliminating the URL-domain-inference workaround.

3. **`new-protocol/SKILL.md`** — apply the same flag-aware rendering when the skill body is composed. If both sources are enabled it reads "external repositories (OpenWetWare and protocols.io). The subagent picks the best source for the query." Otherwise it reads only the enabled source name. If both are off, the external-repository bullet is omitted from the skill body.

4. **Subagent prompt and connector code** — no change. Already correct.

### Tests

- **Unit** `backend/tests/unit/test_chat_agent_prompt_rendering.py` (new):
  - Both sources on → rendered prompt mentions both names; section heading contains both.
  - Only OpenWetWare on → rendered prompt mentions OpenWetWare, does NOT mention protocols.io.
  - Only protocols.io on → mirror case.
  - Master flag off → rendered prompt has neither source name AND drops the subagent one-liner.
- **Unit** `backend/tests/unit/test_new_protocol_skill_rendering.py` (new) — same matrix for the skill body.
- **Unit** `backend/tests/unit/test_protocol_knowledgebase_tools.py` (extend existing or new) — the public result type carries `source_label` of `"OpenWetWare"` or `"protocols.io"` based on the connector.
- **Integration** — covered by the Sub-issue #1 integration test above which already exercises a `send_message` round-trip; no new integration test needed here.

## Sub-issue #4 — Library image-extraction `Errno 2`

### Cause (suspected; needs reproduction)

Uploading an image (PNG/JPG) to the library fails with `Extraction error: [Errno 2] No such file or directory`. The error is surfaced via `backend/app/services/documents/extraction/extract_job.py:173` which truncates the docling subprocess's stderr to 500 chars.

Likely root cause: `ext/docling-extractor/docling_extractor/pipeline.py:build_converter` only registers `InputFormat.PDF`. Image inputs fall through to a default route that may try to read a missing model cache or write to a missing temp directory. Two other plausible causes:

- EasyOCR model cache not present on the subprocess side for an image-only code path.
- A pillow/docling temp file path that requires a working dir that doesn't exist when the subprocess runs.

The 500-char truncation hides the full traceback, which is the *first* thing to fix so the next person to hit this can diagnose it without code changes.

### Approach

1. **Stop truncating stderr — promoted to actual fix, not optional.**
   - In `extract_job.py:173`, store the full stderr (capped at a safe upper bound, e.g. 64 KB) on the document's `error_message` field, or store the truncated form on `error_message` and the full form on a new `error_message_full` column / `Document.extraction_error_log` JSONB field. Pick whichever requires less migration churn — `error_message` is `Text` in postgres so just removing the `[:500]` cap is the minimal fix. Do that.
   - Add a structured `logger.error("docling stderr (truncated for log): %s", msg[:2000])` next to `_persist_failure` so the docker logs have a server-side copy regardless of DB storage.

2. **Reproduce + diagnose** (time-boxed to 90 minutes from when the worktree is ready):
   - Upload a small PNG via the library UI in dev with the un-truncated stderr in place. Capture the full traceback from logs.
   - If root cause is identified in the time box → apply the precise fix (Step 3a).
   - If root cause is NOT identified in the time box → apply the defensive fix (Step 3b). Don't keep diagnosing.

3a. **Precise fix** in `ext/docling-extractor/` based on diagnosis. Most likely landing spots:
   - Register `InputFormat.IMAGE` in `build_converter` with an appropriate `PipelineOptions`.
   - Pre-create the cache/temp directory the pipeline writes to.

3b. **Defensive fix** (apply if 3a's root cause is unknown after the time box):
   - In `build_converter`, register both `InputFormat.PDF` and `InputFormat.IMAGE` with explicit options. The docling docs list IMAGE as a supported format; the omission is almost certainly the bug.
   - In the image branch, set `do_ocr=False` initially (we can't be sure the OCR model is downloaded). Document this as a known-degraded path for image extraction.
   - Wrap the docling `convert(...)` call in a `try/except` that catches `FileNotFoundError` specifically and re-raises with the missing path appended to the message — so the next failure mode (whatever it is) is self-diagnosing.

   The defensive fix is intentionally conservative: it adds the obviously-correct registration and improves diagnostics; it does not guess at the model-cache or temp-dir question if we haven't confirmed it.

4. **Regression test** in `ext/docling-extractor/tests/test_image_extraction.py` (new):
   - Add a tiny PNG fixture `tests/fixtures/tiny.png` (64×64 solid color, generated and checked in).
   - Test calls `main()` directly with `--input tests/fixtures/tiny.png --output-dir <tmp>` and asserts exit 0 plus the presence of `refined.md` and `result.json`.
   - The test runs with `do_ocr=False` so it does not need the EasyOCR model cache — committing to integration over mock here because the bug being fixed is in the docling-call path itself; a mock that returns a stub `ExtractionResult` would not have caught the original bug.
   - If the test environment cannot load docling at all (e.g. CI has no GPU and docling refuses to import), mark the test `@pytest.mark.requires_docling` and skip when the import fails; document the marker in `ext/docling-extractor/conftest.py`.

5. **Validate the un-truncation fix independently** — add a unit test in `backend/tests/unit/test_extract_job.py` (new or extend) that simulates a 1000-character stderr and asserts the persisted `error_message` is not truncated to 500.

### Tests

Covered above. The image-extraction regression test must fail on `main` before the fix and pass after.

## Sequencing

Single worktree, three commits, in this order:

1. **Sub-issue #1** (shared helper + refactor + tool-result fields + prompt + sanitizer + tests + e2e integration test).
2. **Sub-issue #2** (prompt-rendering refactor + `source_label` + assertions).
3. **Sub-issue #4** (un-truncate stderr → diagnose → fix → regression test).

Each commit uses TDD red→green→refactor. After all three, run the full backend test suite (`pytest`) and the docling-extractor suite.

## Browser verification (required)

These bugs surface in the browser. Tests prove correctness in isolation; browser verification proves the user-visible bug is actually gone. Run through chrome with `qa-verify` after all three commits land:

1. **Sub-issue #1 — protocol link in chat:**
   - Open the chat panel, ask the agent to create a new protocol (e.g., "Create a protocol for buffer mixing").
   - When the agent emits the markdown link in its response, click it.
   - **Pass criterion:** The URL is `/{org-slug}/protocols/{protocol-slug}` and the protocol page loads (no 404). The URL must NOT contain a UUID after `/protocols/`.
   - Verify in a second org (or as a multi-org user if available) that the slug disambiguation works when two orgs collide; if no collision exists in dev, this can be deferred to manual QA notes.

2. **Sub-issue #2 — protocols.io advertisement:**
   - In chat, ask: "What sources can you derive protocols from?"
   - **Pass criterion:** With both `openwetware` and `protocols_io` feature flags on, the agent's reply mentions both OpenWetWare and protocols.io. With only one source flag on, it mentions only that source. With the master flag off, neither is mentioned.
   - Backend feature flag toggling for dev: set `BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ENABLED=true` (and matching `access_token`) and restart the dev server. The three flag-state checks can be done by restarting the backend between them, OR the second/third can be deferred to a unit-test-only assertion if dev flag toggling is too disruptive.
   - Bonus: ask the agent to find a protocol that exists on protocols.io but not OpenWetWare; confirm the citation reads `[protocols.io source](...)` not `[OpenWetWare source](...)`.

3. **Sub-issue #4 — library image extraction:**
   - Open the library, upload a PNG (any small image — e.g., a screenshot).
   - **Pass criterion:** Extraction completes without the `Errno 2` error; the document's status moves from "extracting" to "ready" (or whatever the success state is) and the refined-markdown view shows content.
   - Repeat with a JPG to confirm the fix covers the broader image-input case, not just PNG.

Each pass criterion must be visually confirmed in chrome. If any criterion fails, the fix is incomplete and goes back to the implementation step — do not close BUG-0009 with browser failures outstanding.

`qa-verify` runs these checks; pass it the dev credentials (`localhost:5432`, `postgres`/`postgres`, db `batchrite`) and the three pass criteria above. No frontend code changed, but the user-visible behavior of all three bugs lives in the browser.

## Out of scope

- Chat attachment uploads (#3) — F-0096.
- Any non-chat surface that emits protocol URLs — verified `links.py` already correct; no other consumers were found.
- Stale-URL handling when an org is renamed — same limitation already applies to notification deep links; logged for future only if support reports it.
- Frontend changes — none required for these three sub-issues.
