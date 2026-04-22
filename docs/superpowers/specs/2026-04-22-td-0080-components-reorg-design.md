# TD-0080 — Reorganize `frontend/src/lib/components` into domain subdirectories

**Date:** 2026-04-22
**Status:** Approved (pending spec review)
**ClickUp:** [TD-0080](https://app.clickup.com/t/86e0zg7d6)

## Motivation

`frontend/src/lib/components/` has grown to 39 root-level files mixing modals,
nav chrome, protocol-editor nodes, AI chat, analytics, and field-mode screens.
Discoverability is poor and new contributors place files inconsistently.
Several domain subdirectories already exist (`ui/`, `edra/`, `project/`,
`protocol/`, `run/`, `settings/`) but were never filled out.

## Goals

1. Move every root-level file into a domain subdirectory.
2. Keep imports working — no behavioral changes.
3. Add a written rule so future components land in the right place.

## Non-goals

- No component code changes (no renames, no splits, no API changes).
- No changes to `ui/` or `edra/` contents.
- No new abstractions, shared utilities, or extracted hooks.

## Final directory layout

```
frontend/src/lib/components/
├── ui/              (unchanged)
├── edra/            (unchanged)
├── project/         (unchanged)
├── protocol/        (+6 editor components — see below)
├── run/             (+1: RoleWizard)
├── settings/        (+1: AiSettingsTab)
├── field-mode/      NEW
├── modals/          NEW
├── media/           NEW
├── analytics/       NEW
├── ai/              NEW
├── layout/          NEW
└── shared/          NEW
```

After the move, **no `.svelte` or `.ts` files remain at the root** of
`lib/components/`.

### File → bucket mapping

| File | New location |
|------|--------------|
| `Inspector.svelte` | `protocol/` |
| `UnitOpNode.svelte` | `protocol/` |
| `SwimLaneNode.svelte` | `protocol/` |
| `ProcessStartNode.svelte` | `protocol/` |
| `ProcessStartInspector.svelte` | `protocol/` |
| `TimeAxis.svelte` | `protocol/` |
| `RoleWizard.svelte` | `run/` |
| `AiSettingsTab.svelte` | `settings/` |
| `FieldModeHeader.svelte` | `field-mode/` |
| `FieldModeLockScreen.svelte` | `field-mode/` |
| `FieldModeRoleWizard.svelte` | `field-mode/` |
| `CreateUnitOpModal.svelte` | `modals/` |
| `EquipmentPickerModal.svelte` | `modals/` |
| `ProtocolImportModal.svelte` | `modals/` |
| `TemplateConvertModal.svelte` | `modals/` |
| `BatchRecordImportModal.svelte` | `modals/` |
| `ImageAnalysisDialog.svelte` | `modals/` |
| `DocumentUploadDialog.svelte` | `modals/` |
| `BarcodeScanner.svelte` | `media/` |
| `BarcodeScanner.test.ts` | `media/` |
| `barcodeScannerUtils.ts` | `media/` |
| `ImageGallery.svelte` | `media/` |
| `PdfPreviewDrawer.svelte` | `media/` |
| `CompletionChart.svelte` | `analytics/` |
| `AuditTimeline.svelte` | `analytics/` |
| `VersionHistoryDrawer.svelte` | `analytics/` |
| `ChatPanel.svelte` | `ai/` |
| `ChatSkillButtons.svelte` | `ai/` |
| `MobileNav.svelte` | `layout/` |
| `UserMenu.svelte` | `layout/` |
| `NotificationBell.svelte` | `layout/` |
| `Logo.svelte` | `layout/` |
| `ProjectsDropdown.svelte` | `layout/` |
| `ConnectivityBanner.svelte` | `shared/` |
| `ExpiryWarningBanner.svelte` | `shared/` |
| `ConfidenceBadge.svelte` | `shared/` |
| `MarkdownRenderer.svelte` | `shared/` |
| `ResponsiveTable.svelte` | `shared/` |
| `GoOfflineDialog.svelte` | `shared/` |

## Migration mechanics

1. **Move with `git mv`** so history is preserved and rename detection keeps
   diffs clean.
2. **Update imports** in consumers:
   - Absolute imports (`$lib/components/X.svelte`) become
     `$lib/components/<bucket>/X.svelte`.
   - Relative imports inside components that used to sit at the root (e.g.
     `Inspector.svelte` importing `./EquipmentPickerModal.svelte`) are
     rewritten to absolute `$lib/components/<bucket>/X.svelte` rather than
     brittle `../modals/X.svelte`.
3. **Commit strategy:** one commit per bucket (bucket creation + its files +
   the import updates that target those files). This keeps each diff small
   and reviewable. Final commit is the conventions rule.
4. **Verification:** `npm run check` (svelte-check + tsc) + `npm run test` +
   manual browser smoke of the protocols editor, runs page, field-mode
   entry, and the main layout (nav/chat).

## Guidelines (to add to `.claude/rules/conventions.md`)

Append a subsection to the existing "## DRY" block:

> **Component placement.** New Svelte components under `lib/components/` MUST
> go in a domain subdirectory, not at the root. Choose the most specific
> existing bucket before creating a new one. Buckets:
>
> - `ui/` — shadcn-svelte primitives only (buttons, inputs, dialogs, etc.)
> - `protocol/` — protocol-editor canvas pieces, nodes, inspector, sidebar
> - `project/` — project page tabs and project-scoped dialogs
> - `run/` — run execution surfaces (edit mode, attachments, history)
> - `settings/` — settings page tabs and their modals
> - `field-mode/` — tablet/field-mode flows
> - `modals/` — heavy dialogs that wrap a form, import, or picker flow
>   (contrast with lightweight confirmation dialogs, which go in `shared/`)
> - `media/` — camera, image, PDF, barcode
> - `analytics/` — charts, audit trails, version history
> - `ai/` — chat and agent UX
> - `layout/` — global app chrome (nav, user menu, logo, banners that live
>   in `+layout.svelte`)
> - `shared/` — small cross-cutting presentational pieces (badges, small
>   banners, markdown rendering, generic tables)
>
> If a component is used by only one domain's routes, prefer that domain's
> bucket (`project/`, `run/`, etc.) over `modals/` or `shared/`.

## Risk & rollback

- **Risk:** low. Pure rename refactor, no runtime code paths touched.
- **Detection:** `npm run check` will surface any missed import.
- **Rollback:** revert the worktree commits; no DB or deploy state involved.

## Acceptance criteria (from ClickUp)

- [x] Audit completed and duplicated/mixed concerns identified
- [x] Propose final directory structure with rationale
- [ ] Plan migration without breaking imports (update all references)
- [ ] Establish guidelines for future component placement
