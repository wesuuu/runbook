# TD-0071 — Svelte Transitions Across Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `svelte/transition` and `svelte/animate` primitives to all 15 pages and the root layout so page navigation, loading/error/empty swaps, and list reorders fade smoothly instead of hard-popping.

**Architecture:** A shared `lib/transitions.ts` module exports duration constants and a `prefersReducedMotion` helper. `routes/+layout.svelte` wraps `{@render children()}` in a keyed fade block for page-level transitions. Each page adds `transition:fade` to its loading/error/empty conditionals and `animate:flip` + `in:fade` to key lists. The dashboard replaces its CSS `@keyframes fadeSlideUp` with Svelte `fly`.

**Tech Stack:** Svelte 5 (Runes), `svelte/transition` (`fade`, `fly`), `svelte/animate` (`flip`), Vitest.

## File Structure

- **Create:**
  - `frontend/src/lib/transitions.ts` — duration constants + reduced-motion helpers
  - `frontend/src/lib/transitions.test.ts` — unit tests for above
- **Modify:** all 15 page files listed in the spec plus `routes/+layout.svelte` and `routes/+page.svelte`

---

## Task 1: Create `lib/transitions.ts` module with unit tests

**Files:**
- Create: `frontend/src/lib/transitions.ts`
- Test: `frontend/src/lib/transitions.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/transitions.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
    PAGE_MS,
    BLOCK_MS,
    LIST_MS,
    prefersReducedMotion,
    pageDuration,
    blockDuration,
    listDuration,
} from './transitions';

describe('transitions', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it('exports positive numeric constants', () => {
        expect(PAGE_MS).toBeGreaterThan(0);
        expect(BLOCK_MS).toBeGreaterThan(0);
        expect(LIST_MS).toBeGreaterThan(0);
    });

    it('prefersReducedMotion returns false when matchMedia reports false', () => {
        vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
        expect(prefersReducedMotion()).toBe(false);
    });

    it('prefersReducedMotion returns true when matchMedia reports true', () => {
        vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
        expect(prefersReducedMotion()).toBe(true);
    });

    it('duration helpers return constant when reduced-motion is off', () => {
        vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
        expect(pageDuration()).toBe(PAGE_MS);
        expect(blockDuration()).toBe(BLOCK_MS);
        expect(listDuration()).toBe(LIST_MS);
    });

    it('duration helpers return 0 when reduced-motion is on', () => {
        vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
        expect(pageDuration()).toBe(0);
        expect(blockDuration()).toBe(0);
        expect(listDuration()).toBe(0);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- transitions`
Expected: FAIL — module does not exist

- [ ] **Step 3: Write minimal implementation**

`frontend/src/lib/transitions.ts`:

```typescript
export const PAGE_MS = 150;
export const BLOCK_MS = 120;
export const LIST_MS = 150;

export function prefersReducedMotion(): boolean {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export const pageDuration = (): number =>
    prefersReducedMotion() ? 0 : PAGE_MS;
export const blockDuration = (): number =>
    prefersReducedMotion() ? 0 : BLOCK_MS;
export const listDuration = (): number =>
    prefersReducedMotion() ? 0 : LIST_MS;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- transitions`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/transitions.ts frontend/src/lib/transitions.test.ts
git commit -m "feat(frontend): add transitions module with reduced-motion helpers [TD-0071]"
```

---

## Task 2: Add page-level transition wrapper to root layout

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`

- [ ] **Step 1: Add imports and wrap both `{@render children()}` calls**

Edit `frontend/src/routes/+layout.svelte`. At the top of the `<script>` block, add:

```typescript
import { fade } from 'svelte/transition';
import { pageDuration } from '$lib/transitions';
```

Replace the full-bleed render block (around line 176):

```svelte
{#if isFullBleed || isPublicRoute}
    {@render children()}
{:else}
    <main class="container mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
        {@render children()}
    </main>
{/if}
```

with:

```svelte
{#if isFullBleed || isPublicRoute}
    {#key $page.url.pathname}
        <div in:fade={{ duration: pageDuration() }}>
            {@render children()}
        </div>
    {/key}
{:else}
    <main class="container mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
        {#key $page.url.pathname}
            <div in:fade={{ duration: pageDuration() }}>
                {@render children()}
            </div>
        {/key}
    </main>
{/if}
```

- [ ] **Step 2: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/+layout.svelte
git commit -m "feat(frontend): add page-level fade transition to root layout [TD-0071]"
```

---

## Task 3: Dashboard — replace CSS keyframes and add conditional/list transitions

**Files:**
- Modify: `frontend/src/routes/+page.svelte`

- [ ] **Step 1: Add imports**

At the top of the `<script>` block add:

```typescript
import { fade, fly } from 'svelte/transition';
import { flip } from 'svelte/animate';
import { blockDuration, listDuration } from '$lib/transitions';
```

- [ ] **Step 2: Replace CSS keyframe-driven `style="animation: fadeSlideUp ..."` with Svelte `in:fly`**

Search for every line containing `style="animation: fadeSlideUp`. For each, remove the `style=` attribute and add a Svelte transition:

Example: the counter button at line 275–280 becomes:

```svelte
<button
    class="card-warm rounded-xl p-4 text-left hover:border-primary/30 hover:shadow-md transition-all duration-150 group relative overflow-hidden {counter.link ? 'cursor-pointer' : 'cursor-default'}"
    onclick={() => counter.link ? goto(counter.link) : null}
    in:fly={{ y: 12, duration: blockDuration(), delay: i * 60 }}
>
```

Example: the orphan section at line 301:

```svelte
<section in:fly={{ y: 12, duration: blockDuration(), delay: 50 }}>
```

Apply the same replacement to every `style="animation: fadeSlideUp ..."` in the file. Preserve the stagger delay (convert seconds → milliseconds by multiplying the delay value by 1000, or use `i * 60` for iterated cards).

- [ ] **Step 3: Wrap state-swap `{#if}` blocks with `transition:fade`**

For the loading/error/dashboard outer branches (lines 251, 253, 263), wrap the **inner** top-level element of each branch with `transition:fade={{ duration: blockDuration() }}`.

```svelte
{#if loading}
    <div transition:fade={{ duration: blockDuration() }}>
        <LoadingSpinner message="Loading dashboard..." />
    </div>
{:else if error}
    <div transition:fade={{ duration: blockDuration() }} class="flex flex-col items-center justify-center py-32 gap-4">
        ...existing markup...
    </div>
{:else if dashboard}
    <div transition:fade={{ duration: blockDuration() }} class="max-w-6xl mx-auto">
        ...existing markup...
    </div>
{/if}
```

Replace the existing `<div class="max-w-6xl mx-auto">` wrapper with the transition-wrapped version above.

- [ ] **Step 4: Add `animate:flip` + `in:fade` to the activity feed list**

Around line 517, the activity items iteration becomes:

```svelte
{#each activityItems as item (item.id)}
    <div animate:flip={{ duration: listDuration() }} in:fade={{ duration: listDuration() }}>
        ...existing item markup...
    </div>
{/each}
```

Note: add the `(item.id)` keyed-each expression.

- [ ] **Step 5: Remove the `@keyframes fadeSlideUp` style block**

At the bottom of the file (around line 558–569), remove the entire `<style>` block containing `@keyframes fadeSlideUp`. If there are other styles, keep them and remove only the keyframes rule.

- [ ] **Step 6: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/+page.svelte
git commit -m "feat(frontend): replace dashboard CSS keyframes with Svelte transitions [TD-0071]"
```

---

## Task 4: Auth pages — login, register, check-email

**Files:**
- Modify: `frontend/src/routes/login/+page.svelte`
- Modify: `frontend/src/routes/register/+page.svelte`
- Modify: `frontend/src/routes/check-email/+page.svelte`

Each page has an `{#if error}` (or similar) toast-style conditional. Wrap its inner element with `transition:fade`.

- [ ] **Step 1: Edit `login/+page.svelte`**

At top of `<script>` add:

```typescript
import { fade } from 'svelte/transition';
import { blockDuration } from '$lib/transitions';
```

Around line 55, wrap the error block:

```svelte
{#if error}
    <div transition:fade={{ duration: blockDuration() }} class="...existing classes...">
        {error}
    </div>
{/if}
```

(Keep the existing classes exactly; just add `transition:fade` as an attribute.)

- [ ] **Step 2: Edit `register/+page.svelte`**

Same pattern as login. Add imports, wrap line 62 error block with `transition:fade={{ duration: blockDuration() }}`.

- [ ] **Step 3: Edit `check-email/+page.svelte`**

Same pattern. Add imports, wrap line 197 `{#if searchQuery}` block — but first read lines 190–205 to confirm the block is a state-swap (not a persistent feature toggle). If it is a search/empty swap, wrap it. If it's a static toggle that persists through user interaction, skip it.

- [ ] **Step 4: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/login/+page.svelte frontend/src/routes/register/+page.svelte frontend/src/routes/check-email/+page.svelte
git commit -m "feat(frontend): transition auth page error states [TD-0071]"
```

---

## Task 5: Projects list and detail

**Files:**
- Modify: `frontend/src/routes/projects/+page.svelte`
- Modify: `frontend/src/routes/projects/[id]/+page.svelte`

- [ ] **Step 1: Edit `projects/+page.svelte`**

Add imports:

```typescript
import { fade } from 'svelte/transition';
import { flip } from 'svelte/animate';
import { blockDuration, listDuration } from '$lib/transitions';
```

Wrap the loading/error/empty blocks (lines 53, 55, 64) with `transition:fade={{ duration: blockDuration() }}`.

For the two `{#each projects as project}` blocks (lines 71, 96), add a keyed expression and per-item transitions:

```svelte
{#each projects as project (project.id)}
    <div animate:flip={{ duration: listDuration() }} in:fade={{ duration: listDuration() }} class="...existing classes...">
        ...existing card markup...
    </div>
{/each}
```

Preserve existing outer classes. If the existing markup uses a `<button>` or `<a>` as the top-level item, add `animate:flip` and `in:fade` directly to that element.

- [ ] **Step 2: Edit `projects/[id]/+page.svelte`**

Add imports as above.

Wrap the loading/error/project state swap (lines 238, 244, 250) with `transition:fade={{ duration: blockDuration() }}` on the inner wrappers of each branch.

Do **not** touch the tab-switch `{#if activeTab === ...}` blocks — those are feature toggles, not state swaps.

- [ ] **Step 3: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/projects/+page.svelte frontend/src/routes/projects/\[id\]/+page.svelte
git commit -m "feat(frontend): transition projects pages [TD-0071]"
```

---

## Task 6: Library list and detail

**Files:**
- Modify: `frontend/src/routes/library/+page.svelte`
- Modify: `frontend/src/routes/library/[id]/+page.svelte`

- [ ] **Step 1: Edit `library/+page.svelte`**

Add imports as in Task 5.

Wrap state-swap conditionals with `transition:fade={{ duration: blockDuration() }}`:
- `{#if searching}` / `{#if searchError}` (lines 207, 209)
- `{#if searchResults.length === 0}` (line 230)
- `{#if loading}` / `{#if error}` (lines 265, 267)
- `{#if documents.length === 0}` (line 277)

For the `{#each documents as doc}` lists (lines 287, 318), add keyed expressions `(doc.id)` and `animate:flip` + `in:fade` on each item.

For the `{#each searchResults as group}` (line 236), add a keyed expression based on the group's unique identifier (likely `group.source_id` or `group.name` — verify while editing).

- [ ] **Step 2: Edit `library/[id]/+page.svelte`**

Add imports as above.

Wrap state-swap blocks:
- `{#if loading}` / `{#if error}` / `{#if document}` (lines 308, 310, 312) — wrap inner elements
- Status-dependent blocks (lines 345, 351, 372, 386, 400 etc.) — these are state swaps as the document status changes; wrap them.
- `{#if allChunks.length === 0}` (line 517) — wrap.

For `{#each sectionNav as section}` (line 428) and `{#each allChunks as chunk, i}` (line 529), add `animate:flip` + `in:fade` per item. Use a stable key if available (`chunk.id`).

- [ ] **Step 3: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/library/+page.svelte frontend/src/routes/library/\[id\]/+page.svelte
git commit -m "feat(frontend): transition library pages [TD-0071]"
```

---

## Task 7: Runs detail page

**Files:**
- Modify: `frontend/src/routes/runs/[id]/+page.svelte`

- [ ] **Step 1: Edit `runs/[id]/+page.svelte`**

Add imports:

```typescript
import { fade } from 'svelte/transition';
import { flip } from 'svelte/animate';
import { blockDuration, listDuration } from '$lib/transitions';
```

Wrap the loading/error/not-found state swap:
- `{#if loading}` (line 318) — inner `<LoadingSpinner>` wrapped with `transition:fade`
- `{#if error && !run}` (line 320) — wrap inner element
- `{#if !run}` (line 327) — wrap inner element

Do **not** touch the tab conditionals (`{#if activeTab === 'notes'}`, etc.) — feature toggles.

For conditional status displays (lines 535, 576, 652, 658, 722, 829), wrap each block with `transition:fade={{ duration: blockDuration() }}` on its inner element if it renders a state-dependent panel.

- [ ] **Step 2: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/runs/\[id\]/+page.svelte
git commit -m "feat(frontend): transition run detail state swaps [TD-0071]"
```

---

## Task 8: Protocols and experiments detail pages

**Files:**
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte`
- Modify: `frontend/src/routes/experiments/[id]/+page.svelte`

- [ ] **Step 1: Edit `protocols/[id]/+page.svelte`**

Add imports:

```typescript
import { fade } from 'svelte/transition';
import { blockDuration } from '$lib/transitions';
```

Wrap `{#if loading}` (line 1019) inner element with `transition:fade={{ duration: blockDuration() }}`. Leave the node-selection and dialog conditionals alone (they're panel toggles, not state swaps).

- [ ] **Step 2: Edit `experiments/[id]/+page.svelte`**

Add imports (including `flip`, `listDuration`).

Wrap loading/error/experiment state swap (lines 139, 141, 143) with `transition:fade={{ duration: blockDuration() }}`.

For `{#each notes as note}` (line 270), add `(note.id)` key plus `animate:flip` + `in:fade`.

For `{#each note.flags as flag}` (line 284), add a key based on `flag.id` or `flag.name` if available, plus `animate:flip` + `in:fade`.

- [ ] **Step 3: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/protocols/\[id\]/+page.svelte frontend/src/routes/experiments/\[id\]/+page.svelte
git commit -m "feat(frontend): transition protocol and experiment detail pages [TD-0071]"
```

---

## Task 9: Chat page

**Files:**
- Modify: `frontend/src/routes/chat/+page.svelte`

- [ ] **Step 1: Edit `chat/+page.svelte`**

Add imports:

```typescript
import { fade } from 'svelte/transition';
import { flip } from 'svelte/animate';
import { blockDuration, listDuration } from '$lib/transitions';
```

Wrap state-swap conditionals with `transition:fade={{ duration: blockDuration() }}`:
- `{#if sessions.length === 0 && !loading}` (line 95)
- `{#if !activeSession}` (line 132)
- `{#if activeSession.messages.length === 0}` (line 190)
- `{#if sending}` (line 267)
- `{#if messageError}` (line 315)
- `{#if sourcePanelOpen && activeSources.length > 0}` (line 331)

Do **not** wrap per-message role conditionals (`{#if msg.role === 'assistant'}`, etc.) — those swap content *within* an existing message, not across states.

For `{#each sessions as session (session.id)}` (line 100, already keyed), add `animate:flip={{ duration: listDuration() }}` + `in:fade={{ duration: listDuration() }}` to each session item.

For `{#each activeSession.messages as msg (msg.id)}` (line 196, already keyed), add `animate:flip` + `in:fade` so new messages fade in rather than hard-pop.

For `{#each activeSources as source, i}` (line 346), change key to `(source.id || i)` and add `animate:flip` + `in:fade`.

- [ ] **Step 2: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/chat/+page.svelte
git commit -m "feat(frontend): transition chat sessions, messages, and source panel [TD-0071]"
```

---

## Task 10: Field mode page

**Files:**
- Modify: `frontend/src/routes/field/+page.svelte`

- [ ] **Step 1: Edit `field/+page.svelte`**

Add imports:

```typescript
import { fade } from 'svelte/transition';
import { blockDuration } from '$lib/transitions';
```

Wrap state-swap conditionals with `transition:fade={{ duration: blockDuration() }}`:
- `{#if !ready}` (line 151) — wrap inner loading markup
- `{#if fieldState === 'locked'}` (line 158) — wrap inner element
- `{#if snapshot}` (line 163) — wrap the inner panel
- `{#if online && queueCount > 0}` (line 193) — wrap inner element (pending-upload banner)

- [ ] **Step 2: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/field/+page.svelte
git commit -m "feat(frontend): transition field mode state swaps [TD-0071]"
```

---

## Task 11: Settings page

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte`

- [ ] **Step 1: Edit `settings/+page.svelte`**

Add imports:

```typescript
import { fade } from 'svelte/transition';
import { flip } from 'svelte/animate';
import { blockDuration, listDuration } from '$lib/transitions';
```

Do **not** wrap tab conditionals (`{#if activeTab === 'organization'}`, etc.) — those are navigation, not state swaps.

Wrap loading/error/empty state swaps within each tab:
- `{#if membersLoading}` / `{#if membersError}` (lines 688, 692) — wrap inner markup
- `{#if teamsLoading}` (line 832) — wrap inner markup
- `{#if teams.length === 0}` (line 834) — wrap inner markup
- `{#if avatarUploading}` (line 898) — wrap inner markup
- `{#if passwordError}` / `{#if passwordMessage}` (lines 972, 979) — wrap inner markup
- `{#if channelsLoading}` (line 1044) — wrap inner markup
- `{#if channels.length === 0 && !showAddChannel}` (line 1046) — wrap inner markup

For `{#each teams as team}` (line 838), add `(team.id)` key + `animate:flip` + `in:fade`.

For `{#each channels as channel}` (line 1055), add `(channel.id)` key + `animate:flip` + `in:fade`.

Skip `{#each EVENT_TYPES as evt}` and `{#each CHANNEL_TYPES as ct}` — static arrays, no reorder.

- [ ] **Step 2: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "feat(frontend): transition settings tabs state swaps and lists [TD-0071]"
```

---

## Task 12: Export page

**Files:**
- Modify: `frontend/src/routes/export/+page.svelte`

- [ ] **Step 1: Edit `export/+page.svelte`**

Add imports:

```typescript
import { fade } from 'svelte/transition';
import { flip } from 'svelte/animate';
import { blockDuration, listDuration } from '$lib/transitions';
```

Wrap state-swap conditionals with `transition:fade={{ duration: blockDuration() }}`:
- `{#if loading}` (line 391) — wrap inner markup
- `{#if error}` (line 393) — wrap inner markup
- `{#if runIds.length === 0}` (line 401) — wrap inner markup
- `{#if rows.length === 0}` (line 409) — wrap inner markup
- `{#if copyFeedback}` (line 267) — wrap inner element (the toast)
- `{#if downloading}` (line 286) — wrap inner element

Do **not** wrap `{#if presetOpen}` or `{#if totalPages > 1}` — those are UI toggles, not state swaps.

For `{#each pagedRows as row, i}` (line 437), change key to `(row.id || i)` and add `animate:flip={{ duration: listDuration() }}` + `in:fade={{ duration: listDuration() }}`.

- [ ] **Step 2: Run type check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/export/+page.svelte
git commit -m "feat(frontend): transition export page state swaps and paged rows [TD-0071]"
```

---

## Task 13: Full verification

**Files:** none modified

- [ ] **Step 1: Run type check**

Run: `cd frontend && npm run check`
Expected: 0 errors.

- [ ] **Step 2: Run unit tests**

Run: `cd frontend && npm run test`
Expected: all tests pass including the new `transitions.test.ts`.

- [ ] **Step 3: Confirm no stray `@keyframes fadeSlideUp` or `style="animation: fadeSlideUp ...` remain**

Run: `cd frontend && grep -rn "fadeSlideUp" src/ || echo "clean"`
Expected: `clean` (no matches).

- [ ] **Step 4: Confirm no remaining files import neither transitions nor have state swaps**

Run: `cd frontend && grep -L "svelte/transition" src/routes/*/+page.svelte src/routes/+page.svelte src/routes/+layout.svelte`
Expected: should list only pages that genuinely have no state-swap blocks (review manually).

- [ ] **Step 5: Manual browser verification via qa-verify agent**

Delegated to the implement-task outer loop — run the dev server and launch the qa-verify agent per implement-task skill step 4.
