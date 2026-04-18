# TD-0072 EmptyState Component Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a shared `EmptyState` Svelte component and refactor 8 empty-state sites across the app to use it.

**Architecture:** New component in `$lib/components/ui/empty-state/` following the shadcn-svelte folder pattern (barrel `index.ts` + `.svelte`). Uses existing `Button` component for the action and `transition:fade` on mount. Callers pass the icon as a Svelte Snippet, keeping the component agnostic to icon libraries.

**Tech Stack:** Svelte 5 (Runes), TailwindCSS 4, `svelte/transition`, existing `Button` component, `cn` utility.

**Spec:** `docs/superpowers/specs/2026-04-17-td-0072-empty-state-component-design.md`

---

## File Structure

**Create:**
- `frontend/src/lib/components/ui/empty-state/empty-state.svelte` — the component
- `frontend/src/lib/components/ui/empty-state/index.ts` — barrel re-export

**Modify:**
- `frontend/src/routes/+page.svelte` — two empty states (dashboard, activity)
- `frontend/src/routes/projects/+page.svelte` — one
- `frontend/src/routes/library/+page.svelte` — two (search results + docs list)
- `frontend/src/routes/chat/+page.svelte` — one
- `frontend/src/routes/export/+page.svelte` — two

**No unit tests for the component itself.** The project's `vitest.config.ts` runs in the default node environment (no jsdom), and existing frontend tests (`BarcodeScanner.test.ts`) test utility logic rather than rendered components. Setting up jsdom + @testing-library/svelte infra is out of scope for a P2 tech-debt task. Verification is done via `svelte-check` (type-safety on all call sites) + browser verification by `qa-verify` agent.

---

### Task 1: Create the EmptyState component

**Files:**
- Create: `frontend/src/lib/components/ui/empty-state/empty-state.svelte`
- Create: `frontend/src/lib/components/ui/empty-state/index.ts`

- [ ] **Step 1: Create the component file**

Create `frontend/src/lib/components/ui/empty-state/empty-state.svelte`:

```svelte
<script lang="ts">
	import type { Snippet } from "svelte";
	import { fade } from "svelte/transition";
	import { cn } from "$lib/utils";
	import { Button } from "$lib/components/ui/button";

	interface Props {
		icon?: Snippet;
		title: string;
		description?: string;
		actionLabel?: string;
		onAction?: () => void;
		class?: string;
	}

	let {
		icon,
		title,
		description,
		actionLabel,
		onAction,
		class: className,
	}: Props = $props();
</script>

<div
	class={cn("flex flex-col items-center text-center py-10", className)}
	transition:fade={{ duration: 200 }}
>
	{#if icon}
		<div
			class="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mb-4 text-muted-foreground/40"
		>
			{@render icon()}
		</div>
	{/if}
	<p class="font-semibold text-foreground">{title}</p>
	{#if description}
		<p class="text-sm text-muted-foreground mt-1 max-w-md">{description}</p>
	{/if}
	{#if actionLabel}
		<Button
			variant="outline"
			size="sm"
			class="mt-4"
			onclick={onAction}
		>
			{actionLabel}
		</Button>
	{/if}
</div>
```

- [ ] **Step 2: Create the barrel export**

Create `frontend/src/lib/components/ui/empty-state/index.ts`:

```typescript
export { default as EmptyState } from "./empty-state.svelte";
```

- [ ] **Step 3: Type-check**

Run from `frontend/`:
```bash
npm run check
```
Expected: PASS (no new errors introduced)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/ui/empty-state/
git commit -m "feat(ui): add shared EmptyState component [TD-0072]"
```

---

### Task 2: Refactor dashboard "No runs yet" empty state

**Files:**
- Modify: `frontend/src/routes/+page.svelte:487-504`

- [ ] **Step 1: Check imports at top of file**

Read the top of `frontend/src/routes/+page.svelte`. If `EmptyState` is not imported, you'll add it. If a `ClipboardList` / appropriate lucide icon is needed, check if `lucide-svelte` is already imported for other icons in the file.

- [ ] **Step 2: Add import**

In the `<script>` block at top of `frontend/src/routes/+page.svelte`, add:

```typescript
import { EmptyState } from "$lib/components/ui/empty-state";
```

- [ ] **Step 3: Replace the markup at lines 487-504**

Replace the existing block:

```svelte
{#if dashboard.my_work.needs_action.length === 0 && dashboard.my_work.active_runs.length === 0 && dashboard.my_work.recently_completed.length === 0 && dashboard.my_work.planned_runs.length === 0}
    <div class="card-warm rounded-xl p-14 text-center" style="animation: fadeSlideUp 0.4s ease-out 0.2s both">
        <div class="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-4">
            <svg class="w-8 h-8 text-muted-foreground/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
        </div>
        <p class="font-semibold text-foreground mb-1">No runs yet</p>
        <p class="text-sm text-muted-foreground mb-5">Get started by creating a project and running a protocol.</p>
        <button
            class="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:text-primary/80 transition-colors duration-150 cursor-pointer"
            onclick={() => goto('/projects')}
        >
            View Projects
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
    </div>
{/if}
```

With:

```svelte
{#if dashboard.my_work.needs_action.length === 0 && dashboard.my_work.active_runs.length === 0 && dashboard.my_work.recently_completed.length === 0 && dashboard.my_work.planned_runs.length === 0}
    <div class="card-warm rounded-xl" style="animation: fadeSlideUp 0.4s ease-out 0.2s both">
        <EmptyState
            title="No runs yet"
            description="Get started by creating a project and running a protocol."
            actionLabel="View Projects"
            onAction={() => goto('/projects')}
            class="py-14"
        >
            {#snippet icon()}
                <svg class="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
                </svg>
            {/snippet}
        </EmptyState>
    </div>
{/if}
```

Rationale: keep the `card-warm` wrapper + entry animation; replace the inner centered markup. Icon wrapper color is already `text-muted-foreground/40` inside `EmptyState`.

---

### Task 3: Refactor dashboard "No recent activity" empty state

**Files:**
- Modify: `frontend/src/routes/+page.svelte:511-514`

- [ ] **Step 1: Replace markup**

Replace:

```svelte
{#if activityItems.length === 0}
    <div class="p-10 text-center">
        <p class="text-sm text-muted-foreground">No recent activity.</p>
    </div>
{/if}
```

With:

```svelte
{#if activityItems.length === 0}
    <EmptyState title="No recent activity" />
{/if}
```

(`EmptyState` already provides centered, muted, `py-10` treatment.)

- [ ] **Step 2: Type-check**

Run from `frontend/`:
```bash
npm run check
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/+page.svelte
git commit -m "refactor(dashboard): use EmptyState component [TD-0072]"
```

---

### Task 4: Refactor `routes/projects/+page.svelte`

**Files:**
- Modify: `frontend/src/routes/projects/+page.svelte:64-67`

- [ ] **Step 1: Add import**

In the `<script>` block, add:

```typescript
import { EmptyState } from "$lib/components/ui/empty-state";
```

- [ ] **Step 2: Replace markup**

Replace:

```svelte
{#if projects.length === 0}
    <div class="text-center py-10 text-muted-foreground">
        No projects found. Create one to get started.
    </div>
{/if}
```

With:

```svelte
{#if projects.length === 0}
    <EmptyState
        title="No projects found"
        description="Create one to get started."
    />
{/if}
```

- [ ] **Step 3: Type-check and commit**

Run `npm run check` (expect PASS), then:

```bash
git add frontend/src/routes/projects/+page.svelte
git commit -m "refactor(projects): use EmptyState component [TD-0072]"
```

---

### Task 5: Refactor `routes/library/+page.svelte` (two sites)

**Files:**
- Modify: `frontend/src/routes/library/+page.svelte:230-233` and `:277-283`

- [ ] **Step 1: Add import**

In the `<script>` block, add:

```typescript
import { EmptyState } from "$lib/components/ui/empty-state";
```

- [ ] **Step 2: Replace search-results empty state (lines 230-233)**

Replace:

```svelte
{#if searchResults.length === 0}
    <div class="text-center py-8 text-muted-foreground">
        No matching documents found.
    </div>
{/if}
```

With:

```svelte
{#if searchResults.length === 0}
    <EmptyState title="No matching documents found" class="py-8" />
{/if}
```

- [ ] **Step 3: Replace document-list empty state (lines 277-283)**

Replace:

```svelte
{#if documents.length === 0}
    <div class="text-center py-10">
        <p class="text-muted-foreground">
            Upload your SOPs, protocols, and reference documents to build your
            searchable knowledge base.
        </p>
    </div>
{/if}
```

With:

```svelte
{#if documents.length === 0}
    <EmptyState
        title="No documents yet"
        description="Upload your SOPs, protocols, and reference documents to build your searchable knowledge base."
    />
{/if}
```

Note: the original was description-only. Adding a title makes the empty state more scannable and matches the consistent treatment across the app (title required by the component API).

- [ ] **Step 4: Type-check and commit**

Run `npm run check` (expect PASS), then:

```bash
git add frontend/src/routes/library/+page.svelte
git commit -m "refactor(library): use EmptyState component [TD-0072]"
```

---

### Task 6: Refactor `routes/chat/+page.svelte`

**Files:**
- Modify: `frontend/src/routes/chat/+page.svelte:95-98`

- [ ] **Step 1: Add import**

In the `<script>` block, add:

```typescript
import { EmptyState } from "$lib/components/ui/empty-state";
```

- [ ] **Step 2: Replace markup**

Replace:

```svelte
{#if sessions.length === 0 && !loading}
    <div class="p-4 text-sm text-muted-foreground text-center">
        No chats yet. Start a new conversation.
    </div>
{/if}
```

With:

```svelte
{#if sessions.length === 0 && !loading}
    <EmptyState
        title="No chats yet"
        description="Start a new conversation."
        class="py-6"
    />
{/if}
```

(`py-6` is slightly tighter than default to fit the sidebar; original used `p-4`.)

- [ ] **Step 3: Type-check and commit**

Run `npm run check` (expect PASS), then:

```bash
git add frontend/src/routes/chat/+page.svelte
git commit -m "refactor(chat): use EmptyState component [TD-0072]"
```

---

### Task 7: Refactor `routes/export/+page.svelte` (two sites)

**Files:**
- Modify: `frontend/src/routes/export/+page.svelte:401-408` and `:409-412`

- [ ] **Step 1: Add import**

In the `<script>` block, add:

```typescript
import { EmptyState } from "$lib/components/ui/empty-state";
```

- [ ] **Step 2: Replace "No runs specified" empty state (lines 401-408)**

Replace:

```svelte
{:else if runIds.length === 0}
    <div class="flex flex-col items-center justify-center py-32 gap-3">
        <div class="text-sm text-slate-400">No runs specified.</div>
        <button
            class="text-sm text-slate-500 hover:text-slate-700 underline transition-colors duration-150 cursor-pointer"
            onclick={goBack}
        >Go back</button>
    </div>
{:else if rows.length === 0}
```

With:

```svelte
{:else if runIds.length === 0}
    <EmptyState
        title="No runs specified"
        actionLabel="Go back"
        onAction={goBack}
        class="py-32"
    />
{:else if rows.length === 0}
```

- [ ] **Step 3: Replace "No data to export" empty state (lines 409-412)**

Replace:

```svelte
{:else if rows.length === 0}
    <div class="flex items-center justify-center py-32">
        <div class="text-sm text-slate-400">No data to export.</div>
    </div>
{:else}
```

With:

```svelte
{:else if rows.length === 0}
    <EmptyState title="No data to export" class="py-32" />
{:else}
```

- [ ] **Step 4: Type-check and commit**

Run `npm run check` (expect PASS), then:

```bash
git add frontend/src/routes/export/+page.svelte
git commit -m "refactor(export): use EmptyState component [TD-0072]"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run svelte-check across the whole frontend**

From `frontend/`:
```bash
npm run check
```
Expected: PASS — no type errors.

- [ ] **Step 2: Run unit tests**

From `frontend/`:
```bash
npm run test
```
Expected: PASS — all existing tests continue to pass.

- [ ] **Step 3: Grep for leftover duplicated empty-state patterns**

```bash
grep -rn "text-center py-" frontend/src/routes/ | grep -E "(No |Upload your|Get started)" || echo "clean"
```
Expected: only already-migrated sites, or "clean".

- [ ] **Step 4: Browser verification (qa-verify agent)**

Start dev servers and hand off to `qa-verify` agent. Test each migrated page in a state that triggers the empty state:
- Dashboard (`/`) — fresh account with no runs → "No runs yet" with icon + action
- Projects (`/projects`) — no projects → "No projects found"
- Library (`/library`) — no documents → "No documents yet"; also search with gibberish → "No matching documents found"
- Chat (`/chat`) — no sessions → "No chats yet"
- Export (`/export` — no `runIds` query param) → "No runs specified" with "Go back"

Verify: centered layout, `transition:fade` on mount, action buttons work, no visual regressions.

The qa-verify agent must fix any FAIL or POLISH issues before returning.

---

### Task 9: User verification gate

**STOP HERE. Do not close the ClickUp task until the user has explicitly confirmed.**

- [ ] **Step 1: Present summary to user**

Post a summary message including:
- Component created + barrel file path
- List of 8 migrated sites (file + line)
- Tests run (svelte-check, unit tests) with pass/fail
- qa-verify report (pages tested, any issues found/fixed)
- Any deviations from the spec

- [ ] **Step 2: Wait for explicit user sign-off**

Ask: "Does this look good to you? Let me know if anything needs adjusting before I close the task."

Do not proceed to Task 10 until the user says yes / looks good / confirms.

If the user requests changes: iterate, re-run `npm run check` + qa-verify as needed, and re-present. Repeat until confirmed.

---

### Task 10: Close the ClickUp task

**Only after explicit user sign-off in Task 9.**

- [ ] **Step 1: Post ClickUp comment**

Use `mcp__clickup__clickup_create_task_comment` on task `86e0w0bdq` (TD-0072) with:
- Summary of what was built
- Files modified (list)
- Commits (hashes or messages)

- [ ] **Step 2: Mark task complete**

Use `mcp__clickup__clickup_update_task` to set status `complete` on `86e0w0bdq`.

---

## Self-Review Checklist

**Spec coverage:**
- [x] New EmptyState component in `$lib/components/ui/empty-state/` — Task 1
- [x] Props: `icon?`, `title`, `description?`, `actionLabel?`, `onAction?` — Task 1
- [x] All 5+ pages refactored — Tasks 2-7 (8 sites across 5 route files)
- [x] Consistent visual treatment (centered, muted, optional icon + CTA) — Task 1 component + per-site migrations
- [x] `transition:fade` on mount — Task 1 (`transition:fade={{ duration: 200 }}`)

**Placeholder scan:** No TBDs, no "similar to Task N", no "add error handling" — each task has full code.

**Type consistency:** All imports use `EmptyState` (named export from barrel). API matches spec exactly (`title`, `description`, `actionLabel`, `onAction`, `icon`, `class`).

**Known deviation from spec:** Spec listed unit tests as "Testing (TDD)". Replaced with `svelte-check` + browser verification because the project doesn't have jsdom configured in vitest (default node env), and existing frontend tests don't render components. Setting up component render infra is out of scope.
