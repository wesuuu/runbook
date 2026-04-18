# Chat Icon Scale Animation & Page Hiding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide the chat floating action button on specific pages and replace the slide animation with a smooth scale animation using Svelte transitions.

**Architecture:** Create a reusable utility function to check if the current path matches any hidden routes. Import it into ChatPanel to control visibility via derived state. Replace CSS keyframe animation with Svelte's `transition:scale` directive.

**Tech Stack:** Svelte 5 (runes, transitions), Vitest (unit tests), regex for route matching

---

## File Structure

```
frontend/src/lib/
  utils/
    chat.ts                    # NEW - shouldHideChatIcon() utility
    chat.test.ts              # NEW - unit tests for utility
  components/
    ChatPanel.svelte          # MODIFY - use utility + Svelte transition
```

---

### Task 1: Create utility function with tests

**Files:**
- Create: `frontend/src/lib/utils/chat.ts`
- Create: `frontend/src/lib/utils/chat.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/utils/chat.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { shouldHideChatIcon } from './chat';

describe('shouldHideChatIcon', () => {
  it('returns true for /chat', () => {
    expect(shouldHideChatIcon('/chat')).toBe(true);
  });

  it('returns true for /chat/ with trailing slash', () => {
    expect(shouldHideChatIcon('/chat/')).toBe(true);
  });

  it('returns true for /chat/sessions', () => {
    expect(shouldHideChatIcon('/chat/sessions')).toBe(true);
  });

  it('returns true for /export', () => {
    expect(shouldHideChatIcon('/export')).toBe(true);
  });

  it('returns true for /protocols/[id] with numeric id', () => {
    expect(shouldHideChatIcon('/protocols/123')).toBe(true);
  });

  it('returns true for /protocols/[id] with uuid', () => {
    expect(shouldHideChatIcon('/protocols/550e8400-e29b-41d4-a716-446655440000')).toBe(true);
  });

  it('returns false for /protocols alone', () => {
    expect(shouldHideChatIcon('/protocols')).toBe(false);
  });

  it('returns false for /protocols/', () => {
    expect(shouldHideChatIcon('/protocols/')).toBe(false);
  });

  it('returns true for /runs/[id] with numeric id', () => {
    expect(shouldHideChatIcon('/runs/456')).toBe(true);
  });

  it('returns false for /runs alone', () => {
    expect(shouldHideChatIcon('/runs')).toBe(false);
  });

  it('returns true for /library/[id] with numeric id', () => {
    expect(shouldHideChatIcon('/library/789')).toBe(true);
  });

  it('returns false for /library alone', () => {
    expect(shouldHideChatIcon('/library')).toBe(false);
  });

  it('returns false for /dashboard', () => {
    expect(shouldHideChatIcon('/dashboard')).toBe(false);
  });

  it('returns false for /protocols/123/edit', () => {
    expect(shouldHideChatIcon('/protocols/123/edit')).toBe(false);
  });

  it('returns false for /runs/456/details', () => {
    expect(shouldHideChatIcon('/runs/456/details')).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend
npm run test -- src/lib/utils/chat.test.ts
```

Expected output: All tests FAIL with "named export 'shouldHideChatIcon' not found"

- [ ] **Step 3: Write the utility function**

Create `frontend/src/lib/utils/chat.ts`:

```typescript
export function shouldHideChatIcon(path: string): boolean {
  return /^\/protocols\/[^/]+$/.test(path) ||
         /^\/runs\/[^/]+$/.test(path) ||
         /^\/library\/[^/]+$/.test(path) ||
         path.startsWith('/chat') ||
         path === '/export';
}
```

- [ ] **Step 4: Run test to verify all pass**

```bash
cd frontend
npm run test -- src/lib/utils/chat.test.ts
```

Expected output: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/utils/chat.ts frontend/src/lib/utils/chat.test.ts
git commit -m "feat: add shouldHideChatIcon utility function with tests"
```

---

### Task 2: Update ChatPanel.svelte to use the utility and Svelte transition

**Files:**
- Modify: `frontend/src/lib/components/ChatPanel.svelte`

- [ ] **Step 1: Import the utility at the top of the script block**

In `frontend/src/lib/components/ChatPanel.svelte`, after line 4 (after the other imports), add:

```typescript
import { shouldHideChatIcon } from '$lib/utils/chat';
```

Full context (lines 1-14):
```typescript
<script lang="ts">
    import { tick } from 'svelte';
    import { marked } from 'marked';
    import DOMPurify from 'dompurify';
    import ChatSkillButtons from '$lib/components/ChatSkillButtons.svelte';
    import { Button } from '$lib/components/ui/button';
    import { shouldHideChatIcon } from '$lib/utils/chat';
    import {
        getPanelState, getActiveSession, getMessageInput, isSending,
        getMessageSources, getSkills,
        openPanel, closePanel, togglePanel,
        setMessageInput, sendMessage, clearConversation,
        registerScrollFn, activateSkill,
    } from '$lib/chat-store.svelte';
```

- [ ] **Step 2: Replace the `isOnChatPage` derived value**

Replace lines 33 with the new derived value:

**Old code (line 33):**
```typescript
const isOnChatPage = $derived(currentPath.startsWith('/chat'));
```

**New code:**
```typescript
const shouldHideChat = $derived(shouldHideChatIcon(currentPath));
```

- [ ] **Step 3: Update the FAB button condition and remove old animation**

Replace lines 88-101 (the entire FAB button block):

**Old code:**
```svelte
{#if panelState === 'collapsed'}
    <Button
        rounded="full"
        class="chat-fab shadow-lg hover:shadow-xl size-14 {isOnChatPage ? 'opacity-40' : ''}"
        style="position:fixed;bottom:1.5rem;right:1.5rem;z-index:40;"
        onclick={() => !isOnChatPage && openPanel()}
        disabled={isOnChatPage}
        aria-label="Open AI Chat"
    >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
            <path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
        </svg>
    </Button>
{/if}
```

**New code:**
```svelte
{#if panelState === 'collapsed' && !shouldHideChat}
    <Button
        transition:scale={{ duration: 200, start: 0 }}
        rounded="full"
        class="chat-fab shadow-lg hover:shadow-xl size-14"
        style="position:fixed;bottom:1.5rem;right:1.5rem;z-index:40;"
        onclick={() => openPanel()}
        aria-label="Open AI Chat"
    >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
            <path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
        </svg>
    </Button>
{/if}
```

**Changes made:**
- Changed condition from `{#if panelState === 'collapsed'}` to `{#if panelState === 'collapsed' && !shouldHideChat}`
- Added `transition:scale={{ duration: 200, start: 0 }}`
- Removed `class` opacity styling (`{isOnChatPage ? 'opacity-40' : ''}`)
- Removed `disabled={isOnChatPage}` attribute
- Removed the guard in `onclick={() => !isOnChatPage && openPanel()}` to just `onclick={() => openPanel()}`

- [ ] **Step 4: Update the keyboard shortcut handler**

Find line 66 (inside `handleGlobalKeydown` function) and update it:

**Old code (lines 63-68):**
```typescript
function handleGlobalKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'j') {
        e.preventDefault();
        if (!isOnChatPage) togglePanel();
    }
}
```

**New code:**
```typescript
function handleGlobalKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'j') {
        e.preventDefault();
        if (!shouldHideChat) togglePanel();
    }
}
```

- [ ] **Step 5: Remove the old CSS animation**

In the `<style>` block (lines 299-309), delete the entire `chat-fab-in` keyframe and the `.chat-fab` rule:

**Old code (lines 300-308):**
```css
@keyframes chat-fab-in {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes chat-panel-in {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}
.chat-fab { animation: chat-fab-in 0.2s ease-out both; }
.chat-panel { animation: chat-panel-in 0.25s ease-out both; }
```

**New code (lines 300-305):**
```css
@keyframes chat-panel-in {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}
.chat-panel { animation: chat-panel-in 0.25s ease-out both; }
```

**Full `<style>` block after changes (lines 299-319):**
```css
<style>
    @keyframes chat-panel-in {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .chat-panel { animation: chat-panel-in 0.25s ease-out both; }
    .chat-prose :global(pre) {
        background-color: hsl(var(--muted));
        border-radius: 0.375rem;
        padding: 0.5rem 0.75rem;
        overflow-x: auto;
        font-size: 0.75rem;
    }
    .chat-prose :global(code) { font-size: 0.75rem; }
    .chat-prose :global(p) { margin-top: 0.375em; margin-bottom: 0.375em; }
    .chat-prose :global(p:first-child) { margin-top: 0; }
    .chat-prose :global(p:last-child) { margin-bottom: 0; }
    .chat-prose :global(ul), .chat-prose :global(ol) {
        margin-top: 0.375em; margin-bottom: 0.375em;
    }
</style>
```

- [ ] **Step 6: Verify the component syntax is correct**

Run the type checker to ensure no TypeScript errors:

```bash
cd frontend
npm run check
```

Expected output: No TypeScript errors or warnings

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/components/ChatPanel.svelte
git commit -m "feat: use shouldHideChatIcon utility and Svelte scale transition for FAB"
```

---

### Task 3: Browser testing on all hidden pages

**Files:**
- No new files (testing only)

- [ ] **Step 1: Start dev servers**

Terminal 1 - Start backend:
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

Terminal 2 - Start frontend:
```bash
cd frontend
npm run dev
```

- [ ] **Step 2: Navigate to /protocols/[id] and verify icon hides**

1. Open `http://localhost:5173/protocols/[any-id]` in browser (e.g., `/protocols/123`)
2. Verify the chat FAB is NOT visible on the page
3. Verify no console errors
4. Navigate back to homepage (`/`)
5. Verify the chat FAB animates in with scale effect (should scale from 0 → 1 smoothly)

- [ ] **Step 3: Navigate to /runs/[id] and verify icon hides**

1. Go to `http://localhost:5173/runs/[any-id]` (e.g., `/runs/456`)
2. Verify the chat FAB is NOT visible
3. Navigate back to `/`
4. Verify the FAB scales in smoothly

- [ ] **Step 4: Navigate to /chat and verify icon hides**

1. Go to `http://localhost:5173/chat`
2. Verify the chat FAB is NOT visible
3. Navigate to any other page
4. Verify the FAB scales in smoothly

- [ ] **Step 5: Navigate to /library/[id] and verify icon hides**

1. Go to `http://localhost:5173/library/[any-id]` (e.g., `/library/789`)
2. Verify the chat FAB is NOT visible
3. Navigate back to `/`
4. Verify the FAB scales in smoothly

- [ ] **Step 6: Navigate to /export and verify icon hides**

1. Go to `http://localhost:5173/export`
2. Verify the chat FAB is NOT visible
3. Navigate back to `/`
4. Verify the FAB scales in smoothly

- [ ] **Step 7: Test keyboard shortcut on hidden pages**

1. Navigate to `/chat`
2. Press Cmd+J (Mac) or Ctrl+J (Windows/Linux)
3. Verify nothing happens (panel should NOT open because route is hidden)
4. Navigate back to `/`
5. Press Cmd+J / Ctrl+J
6. Verify the chat panel opens

- [ ] **Step 8: Test on visible pages**

1. Navigate to `/` (homepage)
2. Verify the chat FAB is visible
3. Click it and verify the chat panel opens correctly
4. Close the panel
5. Verify the FAB scales out smoothly, then scales back in when ready

- [ ] **Step 9: Mark as complete**

Testing complete. All pages tested, animations verified, no errors.

---

## Self-Review Checklist

**Spec Coverage:**
- ✓ Utility function created with tests (requirement: centralize logic)
- ✓ Used in ChatPanel with derived state (requirement: avoid duplication)
- ✓ Svelte transition added (requirement: scale animation)
- ✓ Old CSS keyframe removed (requirement: replace animation)
- ✓ All 5 routes hidden: `/protocols/[id]`, `/runs/[id]`, `/chat`, `/library/[id]`, `/export`
- ✓ Browser testing on all pages

**Placeholder Scan:**
- ✓ All test cases are concrete with expected inputs/outputs
- ✓ All code blocks are complete and ready to copy-paste
- ✓ All commands include exact expected output
- ✓ No "TBD", "TODO", or incomplete instructions

**Type Consistency:**
- ✓ `shouldHideChat` derived state matches `shouldHideChatIcon()` function
- ✓ `transition:scale` parameters consistent across all uses
- ✓ All regex patterns match the spec's route patterns

**No Gaps:**
- ✓ All acceptance criteria addressed
- ✓ Testing covers all 5 hidden pages + keyboard shortcut + normal behavior
- ✓ Unit tests cover edge cases (trailing slashes, parent routes)
