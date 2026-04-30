---
name: TD-0070 Cursor Pointer Polish
description: cursor-pointer and hover transition audit findings; which files had gaps beyond the original PR
type: project
---

TD-0070 added cursor-pointer/hover/transition to interactive elements app-wide. The PR covered the most visible elements but missed several raw `<button>` elements within the same changed files.

**Fixed in QA (not in original PR):**

- `settings/+page.svelte` lines 602-636: All 6 tab nav buttons (Organization/Teams/Profile/Notifications/AI Models/Templates) — had `transition-colors` but no `cursor-pointer` or `duration-150`
- `settings/+page.svelte` lines 998-1018: Font Size (Small/Medium/Large) and Density (Comfortable/Compact) toggle buttons in Profile tab — same omission
- `settings/+page.svelte` line 1129: Channel Type selector buttons in Notifications tab "Add Channel" form
- `export/+page.svelte` lines 341, 347: Long/Wide layout toggle buttons — `transition-colors` but no `cursor-pointer` or `duration-150`
- `export/+page.svelte` line 305: Quick Setup dropdown trigger button
- `export/+page.svelte` line 323: Preset dropdown option buttons
- `export/+page.svelte` lines 220, 397, 405: Back, Retry, Go Back buttons
- `export/+page.svelte` lines 422-430: Column hide buttons in table header
- `export/+page.svelte` lines 468, 476: Preview pagination Prev/Next buttons
- `runs/[id]/+page.svelte`: Start Run (line 517), Go Offline (line 554), Analyze All (line 665), Edit Run (line 806), Edit Again (line 919) action buttons
- `NotificationBell.svelte`: Mark all read button and notification item buttons
- `ChatPanel.svelte`: Clear conversation, Close panel, and Send message buttons
- `MobileNav.svelte`: X close button in drawer header
- `library/[id]/+page.svelte`: Clear search X button, Front Matter toggle, TOC toggle
- `+page.svelte` (dashboard): Sync Now button, Active Runs cards, Recently Completed cards, Planned Runs cards

**Pattern to watch:** Raw `<button>` elements styled with `transition-colors` but missing `cursor-pointer` — the browser default for `<button>` is `default` cursor, not pointer. Always add both.

**False positives in scanner:** Buttons using CSS classes (`.tab-btn` in PdfPreviewDrawer, `.remove-param-btn` in CreateUnitOpModal) correctly define `cursor: pointer` in their `<style>` blocks — scanner can't detect this.

**Why:** cursor-pointer is browser-default for `<a>` but NOT for `<button>`. Devs writing raw `<button>` elements often add hover/transition but forget cursor.

**How to apply:** When reviewing any PR that touches interactive elements, specifically check raw `<button>` elements (not shadcn `<Button>`) — look for `hover:` or `transition-` classes and verify `cursor-pointer` is also present.
