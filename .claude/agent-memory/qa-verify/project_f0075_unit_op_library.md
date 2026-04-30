---
name: F-0075 Unit Operation Library QA Notes
description: QA patterns, edge cases, and verification results for the Unit Op Library abstraction feature
type: project
---

Verified 2026-04-27. Feature passed all acceptance criteria.

**Key patterns learned:**
- Unit ops API endpoint: GET `/science/unit-ops` — returns all ops for the org (library + custom)
- Ops have `library_slug` field: `"core"` for library ops, `null` for custom org/project ops
- Admin reload endpoint: POST `/admin/libraries/reload` — returns `{libraries: [{slug, op_count}]}`
- Non-admin gets 403 on reload endpoint (enforced server-side)

**Protocol editor sidebar (`ProtocolSidebar.svelte`):**
- 3-level: Library (uppercase, font-weight 700, 13px) → Category (mixed case, font-weight 600, 12px) → Op (indented 36px from sidebar edge)
- Search filters on: name, category, library_slug, library display name (NOT description)
- `effectiveCollapse` derived state: during search = empty Set (all open); after clear = `manualCollapse` set (restores manual state)
- Mark highlights use `{@html highlightMatch(...)}` — amber amber `hsla(40, 95%, 60%, 0.4)` background
- Custom ops appear under "Custom (My Org)" library at bottom of ops list
- The `+` add button on categories opens the existing "Create Unit Operation" dialog via `onOpenCreateModal` callback
- Scope dot: blue = org, green = project

**Settings page (`/settings?tab=organization`):**
- "Unit Operation Libraries" section only renders when `isOrgAdmin` is true
- Button is 138px wide — correctly NOT full-width, sits at `flex-start` within `flex items-center gap-3`
- Toast format: title "Libraries reloaded", description "1 libraries, 12 ops"
- "Last reloaded: Xs ago" timestamp shown after successful reload

**Pre-existing issue (not F-0075):**
- scientist1 accessing settings page logs a browser-level "Failed to load resource: 403" for the members API call. The catch block handles it gracefully (members = []), but the network error still appears in browser console. Pre-existing before F-0075.

**Why:** Established understanding of the feature's full scope for future maintenance or regression testing.
**How to apply:** When testing protocol editor sidebar or settings org tab, check these specific behaviors.
