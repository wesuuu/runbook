# BUG-0008 — Protocol editor UI fixes: time-mode node squish + equipment dialog

## Problem

Two unrelated layout bugs on the protocol-editor canvas surface:

1. **Time-enabled unit op nodes squish their text.** When time mode is toggled
   on, every unit-op node's width is driven by its duration:
   `width = (duration_min / 60) * pixelsPerHour`. A 30-min step at the default
   200 px/hr is only 100 px wide, but the param labels/values inside have no
   truncation rules — they wrap one character per line, producing the screenshot
   in the QA log.
2. **Inline "Create Equipment" form is broken in three ways:**
   - The `+ Add New Equipment` / `✕ Cancel` link toggle sits *above* the form
     fields (between the equipment list and the inputs), not in the form's
     footer next to its submit button.
   - The dialog has nested scrollers — `.equipment-modal` (`max-height: 500px;
     overflow-y: auto`) plus `.equipment-list` (`overflow-y: auto`) — and the
     outer scrollbar ends up visible but unmovable when content sits between
     the two.
   - The raw `<input class="form-input">` background and the `.create-form`
     panel background are too close (both essentially `--muted`), so fields
     visually blend into the panel.

## Goal

Restore readable nodes in time-mode and ship a cleanly-formatted Create Equipment
form: conventional form layout, a single scroll region, footer actions in the
expected place, clearly delineated inputs.

## Approach

### Bug 1 — time-mode node squish

Pick the approach the user signed off on during brainstorm: **truncate with
ellipsis**. Preserves the visual `width = duration` mapping (the whole point of
time-mode); just stops content from wrapping when the node is narrow.

Concrete changes in `frontend/src/lib/components/protocol/UnitOpNode.svelte`:

- `.param-row` — keep flex, ensure children can shrink (`min-width: 0`).
  Add `title={`${label}: ${value}`}` on the row so the full text is reachable
  via native hover tooltip when truncation kicks in.
- `.param-label` — `white-space: nowrap; overflow: hidden; text-overflow:
  ellipsis;`, keep `flex-shrink: 0`, but cap with `max-width: 60%` so the
  label can still ellipsis on extreme widths while the value (which carries
  the user data) is the one that truncates first.
- `.param-value` — `white-space: nowrap; overflow: hidden; text-overflow:
  ellipsis; min-width: 0;` (and keep `text-align: right`). Add `title={value}`
  for the same reason as `.param-row`.
- `.node-params` — `overflow: hidden;` so no child can spill out.
- `.unit-op-node` — keep `min-width: 120px` so the *unconstrained* node still
  looks like an actual node; the timeline-sized inline `width` on the outer
  xyflow wrapper continues to override that visually for short durations, but
  the inner content now truncates instead of wrapping.

No JS / no graph-schema changes. No change to `applyTimelineSizing` (we
explicitly rejected the min-width floor option — it would break visual = duration
on short steps).

### Bug 2 — equipment dialog formatting

Implementation matches the mockup at
`docs/superpowers/specs/2026-05-22-bug-0008-equipment-form-mockups/option-b-css-only.html`.
We keep the existing raw `<input class="form-input">` markup (no migration to
the shared shadcn `Input`) and ship a focused CSS + structural fix in
`frontend/src/lib/components/modals/EquipmentPickerModal.svelte`.

Four changes, all local to that file:

1. **Cancel moves into the form footer.**
   - Remove the standalone `Button variant="link"` toggle (the `+ Add New
     Equipment` / `✕ Cancel` line at the top of `.create-section`).
   - In pick mode, replace it with a single `+ Add New Equipment` button that
     only *opens* the form (no longer doubles as Cancel). When the inline
     form is expanded, hide that "+ Add New Equipment" button so there is
     exactly one entry point on screen at a time.
   - Inside `.create-form`, append a `.create-form-footer` row containing:
     a secondary "Discard" button (closes the form, resets fields) and the
     existing primary "Create Equipment" submit. We use "Discard" (not
     "Cancel") so it's not confused with the outer dialog's "Cancel" button
     that lives on the dialog footer. Remove the standalone full-width
     Create Equipment button from the form body.
   - In `mode === 'create'` (the dedicated Create-only modal), keep only
     "Create Equipment" in the form footer (no Discard — the dialog's own
     close handles that).

2. **Single body scroller, with sticky search.**
   - Remove `max-height: 500px` from `.equipment-modal` (the dialog already
     caps height via `Dialog.Content max-h-[85vh] flex flex-col`).
   - Remove `overflow-y: auto` from `.equipment-list` (it stays a bordered
     panel, but no longer scrolls independently).
   - `.equipment-modal` keeps its `overflow-y: auto` and gains `min-height: 0`
     so it becomes the single scrollable body region inside the flex column
     (matching the mockup).
   - **Sticky search.** The existing search input row becomes
     `position: sticky; top: 0; background: hsl(var(--background)); z-index: 1;`
     inside the scroller so it stays reachable when long equipment lists push
     the inline form off-screen.
   - **"Jump to form" link.** When the inline form is open and the user has
     scrolled the list, render a small inline link "Jump to form ↓" (rendered
     as a `Button variant="link"` aligned to the right of the search row) that
     scrolls `.create-form` into view with `scrollIntoView({block: 'nearest'})`
     (see point 4 — we're also changing the existing autoscroll to use
     `nearest` so we never get a jarring jump-to-bottom when the form opens).
     The link only renders when the form is open AND the form is currently
     out of view; gate via `IntersectionObserver` on `.create-form`.

3. **Visual contrast for inputs (theme-token only).**
   - `.create-form` — switch off `background-color: hsl(var(--muted))` onto
     `background-color: hsl(var(--muted) / 0.4)` so the panel is a softer
     muted tint that exists in every theme. Replace the previously-proposed
     3-px raw primary stripe with a Tailwind-style callout treatment:
     `border-left: 4px solid hsl(var(--primary)); background-color:
     hsl(var(--primary) / 0.05);` so it composes with the muted tint cleanly
     and reads as a callout family across `lab-glass`, `blueprint`, and
     `apothecary` themes.
   - `.form-input` — keep raw-input shape; change `background:
     hsl(var(--background))` → `background: hsl(var(--card))`. On most themes
     `--card` and `--background` are the same shade of white-ish, but where
     they diverge (e.g. `apothecary`) `--card` is the surface intended to sit
     on a tinted panel, which is exactly our situation here. Border stays
     `1px solid hsl(var(--border))`.

4. **Form-open autoscroll is gentler.** The existing
   `createSectionEl?.scrollIntoView({ behavior: 'smooth', block: 'end' })`
   effect (line 127-132 today) becomes `block: 'nearest'`. `'end'` yanks the
   user past the form fields to a near-empty footer; `'nearest'` brings the
   form into view without overshooting and is friendlier for tablets where
   the dialog body is the only scroll surface.

### Bonus cleanup — theme-token-ify hardcoded hex

The same file currently carries two stray hardcoded color literals that
predate this change but live next to code we're touching, so swap them while
the file is open:

- `.type-badge` (line ~617-625): `background: #e0f2fe; color: #0369a1;` →
  `background: hsl(var(--accent)); color: hsl(var(--accent-foreground));`.
- `.error-message` (line ~763-770): `background: #fee2e2; color: #991b1b;` →
  `background: hsl(var(--destructive) / 0.1); color: hsl(var(--destructive));`.

These are theme-token replacements only — no layout/behavioral changes — so
they roll into the same commit as Bug 2.

Nothing else changes: schema, props, callbacks, the conflict / shareable logic,
the create-only mode flow, the SitePicker integration, etc. all stay.

### Non-goals

- **Not** migrating the form to the shared shadcn `Input` component
  (Option A) — the user picked Option B in brainstorm. Tracked future cleanup
  belongs in a TD-* task if we want consistency across the app later.
- **Not** changing `applyTimelineSizing`, `resizeNodeForTimeline`, or the
  NodeResizer `minWidth` (60 stays). The only fix is letting node *content*
  truncate.
- **Not** adopting the shadcn `Input` look elsewhere; only the
  `EquipmentPickerModal` is touched.

## Testing

- **`UnitOpNode`** — add a Vitest unit test (`frontend/src/lib/components/protocol/UnitOpNode.test.ts`)
  that mounts a `UnitOpNode` with a long `data.params` value
  (e.g. `reagents: "PBS + 10% FBS + pen-strep"`). jsdom does not run real
  layout, so we cover the CSS contract *behaviorally*:
  - Assert that `.param-value` has the truncation CSS in its scoped stylesheet
    (read from `getComputedStyle` is unreliable in jsdom for inherited
    text properties, so prefer `el.classList.contains('param-value')` plus an
    inline style spot-check, or — more robust — a snapshot test of the
    component's rendered HTML structure with the long value present).
  - Assert that the rendered `.param-row` has a `title` attribute containing
    both the param label and the param value (regression guard for the
    accessibility / tooltip fallback when truncation kicks in).
  - Assert that `.param-value` has a `title` attribute equal to the raw value.
  This combination — structural snapshot + the explicit `title` assertions —
  gives us the regression coverage we want without depending on jsdom's
  unreliable computed-style behavior.
- **`EquipmentPickerModal`** — extend the existing
  `frontend/src/lib/components/modals/EquipmentPickerModal.test.ts`:
  - In `pick` mode with the form expanded, a "Discard" button is rendered
    *inside* `.create-form` next to the submit button (not above the form).
  - When the form is open, the "+ Add New Equipment" toggle is **not**
    rendered (single entry point on screen).
  - Opening then clicking the in-form "Discard" closes the form *and* resets
    the fields (existing assertion on form field reset already covers half of
    this — add the closed-state check).
  - No element matches `.equipment-list[style*="overflow"]` (no double
    scroller). Light assertion — sufficient as a regression guard.
  - In `mode === 'create'`, the form footer renders only "Create Equipment"
    (no "Discard") — the dialog's own close handles dismissal. Verify by
    asserting only one button in `.create-form-footer` with text matching
    `/create equipment/i`.
- **Browser verification** — toggle time mode on a protocol with a 5–10 min
  step that has long reagent/volume values, confirm text truncates with `…`
  rather than wrapping and that hovering shows the full value via native
  tooltip. Open Select Equipment → expand the create form, confirm Discard
  sits in the form footer next to Create Equipment, scroll moves smoothly
  with one scrollbar, the search bar stays sticky at the top of the scrolled
  body, the "Jump to form ↓" link appears only when the form is open and
  scrolled out of view, and inputs are visually distinct from the panel
  across all three themes (`lab-glass`, `blueprint`, `apothecary`).

## Files touched

- `frontend/src/lib/components/protocol/UnitOpNode.svelte` — CSS only.
- `frontend/src/lib/components/modals/EquipmentPickerModal.svelte` — template
  restructure (Cancel button location) + CSS (scroller + contrast).
- `frontend/src/lib/components/modals/EquipmentPickerModal.test.ts` — extend.
- New `frontend/src/lib/components/protocol/UnitOpNode.test.ts` (co-located
  next to the component, matching neighbors like `protocolNodes.test.ts`).
