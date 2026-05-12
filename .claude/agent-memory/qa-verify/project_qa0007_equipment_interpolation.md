---
name: QA-0007 Equipment ID Interpolation
description: Findings from browser QA of equipment ID interpolation feature (E-NNN badges, template tokens, PDF unresolved header)
type: project
---

QA-0007 verified equipment ID interpolation feature. Feature works end-to-end for the happy path.

**Why:** Equipment local IDs (E-001, E-002...) are human-readable aliases for UUID-based equipment references. Template tokens `{{E-001_name}}` and `{{E-001_description}}` in step descriptions are resolved during PDF generation.

**Key findings:**
- Backend model mismatch on worktree: branched before QA-0006 merged. DB had `organization_members.roles` (ARRAY) but code referenced old `role` (VARCHAR). Fixed in models/iam.py + 4 endpoint files.
- Equipment chips (E-NNN badges) render correctly in inspector when node has equipment assigned.
- Template hints show `{{E-001_name}} {{E-001_description}}` tokens in yellow hint box.
- PDF `X-Unresolved-Placeholders` header IS returned when tokens can't resolve. Verified via httpx directly (not Playwright) because draft-save doesn't update Protocol.graph; main save does.
- Duplicate ID detection: cannot test via Playwright because SvelteFlow protocol canvas renders overlapping nodes at same screen position (nodes at x=376, y=417 in default graph layout). The onchange handler in Svelte 5 also doesn't fire via Playwright's check()/click() on checkboxes.
- "Create Equipment" button was hidden below dialog footer at 768px viewport height. Fixed with scrollIntoView effect on create-section div.
- Run-level PDF endpoints (/science/runs/{id}/pdf/sop and /batch-record) both return 200.
- Persistence: save_as_draft=true writes to ProtocolVersion table but NOT Protocol.graph. PDF endpoint reads Protocol.graph. To test unresolved token header, must use normal save (no draft) which requires deleting any conflicting draft version first.

**How to apply:** When verifying protocol editor equipment features, use httpx directly to test PDF header behavior rather than relying on the browser PDF download. Canvas nodes may overlap in test data layouts - use `data-id` attribute to target specific nodes but be aware other nodes may intercept clicks.
