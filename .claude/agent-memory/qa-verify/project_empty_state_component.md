---
name: EmptyState shared component — patterns and verification notes
description: Notes on the EmptyState component introduced in TD-0072 — where it lives, how callers use it, and verified behavior
type: project
---

Component location: `frontend/src/lib/components/ui/empty-state/empty-state.svelte`
Export: `frontend/src/lib/components/ui/empty-state/index.ts`

**Props:** `icon?` (Snippet), `title` (required), `description?`, `actionLabel?`, `onAction?`, `class?`

**Default style:** `flex flex-col items-center text-center py-10` — callers override `py-*` via `class` prop.

**Caller-specific padding:**
- Dashboard "No runs yet": `class="py-14"` 
- Dashboard "No recent activity": default `py-10` (no class override)
- Projects: default `py-10`
- Library no docs: default `py-10`
- Library search: `class="py-8"`
- Chat sidebar: `class="py-6"`
- Export no runs: `class="py-32"`
- Export no data: `class="py-32"`

**Icon:** Only site 1 (dashboard "No runs yet") has an icon. Rendered via `{#snippet icon()}` with an SVG clipboard.

**Action buttons:** Only site 1 ("View Projects" → /projects) and site 7 export ("Go back" → history.back()).

**Export URL:** Uses `?runs=` param (NOT `?runIds=` as the task description says).

**404 handling in export:** `/science/export/preview` returns 404 for nonexistent run IDs; this is caught and displayed as "No data to export" EmptyState — intentional, not a bug.

**Chat sidebar:** EmptyState with `py-6` renders inside a 288px-wide sidebar. Despite narrow width, `items-center text-center` centers correctly. `max-w-md` on description doesn't cause overflow since description is short ("Start a new conversation." = 164px).
