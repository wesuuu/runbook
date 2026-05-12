---
name: F-0081 Run Creator Wizard QA
description: Key bugs found and fixed during QA of the full-screen Run Creator Wizard (Phase 3). Critical patterns for future wizard QA.
type: project
---

## Feature: F-0081 Run Creator Wizard (Phase 3)

4-step full-screen wizard: Name → Protocol → Parameters (overrides) → Review.

**Why:** Verified 2026-04-30; covers graph loading, param diff rendering, save-as-version, equipment picker, confirm-on-close.

### Bugs Found and Fixed

**1. Graph loading from versions list (CRITICAL)**
- Root cause: `/science/protocols/{id}/versions` returns `ProtocolVersionListItem` with no `graph` field.
- Wizard's `$effect` was using `selectedVersion.graph` (empty `{}`), producing 0 UO cards on step 3.
- Fix: Use `selectedProtocol.graph` when `isLatestVersion` is true (protocol object always has full graph).
- File: `RunCreatorWizardModal.svelte` — `$effect` watching `selectedVersion`.

**2. Protocol mirror fields not stamped (CRITICAL)**
- Root cause: `RunCreatorUnitOpCard` compares `data.params` against `data.protocol_params` for diff rendering. `protocol_params` wasn't in the graph nodes.
- Result: All params showed "+ ADDED" (isAdded = true because `protocol_params` was `{}`).
- Fix: Stamp `protocol_*` fields onto each unitOp node when initializing `currentGraph` in the wizard.
- Fields: `protocol_params`, `protocol_paramSchema`, `protocol_equipment`, `protocol_description`.
- File: `RunCreatorWizardModal.svelte` — stamping block after graph source selection.

**3. Equipment API endpoint wrong**
- `/equipment` returns 404. Correct path: `/iam/organizations/${org.id}/equipment`.
- Get org via `getCurrentOrg()` from `$lib/auth.svelte`.
- File: `RunCreatorWizardModal.svelte` — equipment fetch in `$effect` on `open`.

**4. Save-as-version needs two-step flow**
- `POST /publish-draft` requires a draft ProtocolVersion row to exist first.
- Fix: Step 1: `PUT /science/protocols/{id}?save_as_draft=true` with `{ graph: cleanGraph }`.
- Step 2: `POST /science/protocols/{id}/publish-draft?version_number={N}` with `{ description }`.
- Must strip `protocol_*` mirror fields from graph before sending to backend.
- File: `RunCreatorWizardModal.svelte` — `dialogSaveAsVersion()` function.

**5. Equipment picker never opened**
- `RunOverridesEditor` conditioned `EquipmentPickerModal` on `{#if swapNode && onCreateEquipment}`.
- `RunCreatorWizardModal` doesn't pass `onCreateEquipment` prop.
- Fix: Remove `&& onCreateEquipment` gate — condition only on `swapNode`.
- File: `RunOverridesEditor.svelte`.

### UX Notes

- `VersionHistoryDrawer` uses a custom overlay (not shadcn Dialog). Escape does NOT close it. Close via X button with `force: true` in Playwright.
- Diff sidebar (`.diff-aside`) is hidden via media query at viewport < 1100px. At 1024px tablet it collapses to single column — the aside renders below cards, not invisible.
- "stat-lbl Added" text in the diff summary sidebar is a stats legend label, not a param badge. Don't confuse with `.row-tag-amber` "+ ADDED" param badges.
- The "LATEST" pill is `.latest-pill` in `RunCreatorProtocolStep.svelte`.

### How to apply

- When verifying any wizard that uses `$effect` to load a graph from versions list, check that the graph source is `protocol.graph` for latest, not `version.graph`.
- When testing the save-as-version flow, verify the two API calls fire in sequence (PUT first, then POST publish-draft).
- When testing equipment pickers, check the correct IAM org endpoint is used.
