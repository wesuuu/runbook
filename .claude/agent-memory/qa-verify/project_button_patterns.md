---
name: Button component patterns (TD-0075 migration)
description: Button variant usage patterns, semantic exceptions, and QA verification notes from TD-0075 button migration
type: project
---

## Button variant conventions after TD-0075

- `default` = primary dark blue CTA (Save, + New, Submit, Sync Now, Start Import)
- `secondary` = Cancel buttons in dialogs, Try Again
- `outline` = Convert Document, Upload Template, Delete inline (with red class override)
- `destructive` = Only via confirm dialog's `confirmVariant="danger"` mapping
- `ghost` = Icon-only toolbar buttons, sidebar row actions, dropdown trigger items
- `link` = Inline text links (View, Set Default, Archive in tables), All/None column selectors
- `tab` = Page-level tab navigation; combine with `data-active={...}` attribute (not class toggle)

## Semantic amber overrides (allowed)
These use `class` to override colors; they are NOT off-schema drift:
- Go Offline button: `variant="outline"` + `class="border-amber-300 bg-amber-50 text-amber-700"`
- Mark N/A in BatchRecordImportModal: `class="bg-yellow-100 text-yellow-800"`
- Any "Edit Run" or "Analyze All" contextual warning action

## Canvas toolbar (ProtocolEditor)
The CanvasToolbar uses teal `hsl(173, 58%, 39%)` for `data-active` state on mode-toggle and toolbar-btn. This is intentional domain-specific color for the canvas UI — NOT off-schema drift. ProtocolSidebar's save-btn is also teal (intentional brand color for draft saves). Publish button is amber.

## Segmented controls
Used in export page (CSV/Excel/JSON), project detail (User/Team), font size, density preferences.
Pattern: `variant={active ? 'default' : 'ghost'}` or `variant={active ? 'default' : 'outline'}`, all with `class="rounded-none"` in a bordered container div.

## Projects page API error
`/projects` list page shows a backend API validation error (pre-existing on main, unrelated to TD-0075). Not a regression. The API expects `organization_id` query param but the Zod schema validation fails on the response shape.

## QA API endpoint notes (verified April 2026)
- Projects list: `GET /projects/?organization_id={uuid}` 
- Runs list: `GET /science/projects/{project_id}/runs`
- Protocols list: `GET /science/projects/{project_id}/protocols`
- Dashboard: `GET /dashboard?org_id={uuid}`
- Protocol editor route: `/protocols/{id}` (NOT `/library/{id}` which is for library documents)

**Why:** These are non-obvious from routes structure. Library/[id] shows 404 if you pass a protocol ID.
**How to apply:** Always use the correct routes when writing playwright tests for QA.
