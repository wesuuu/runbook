# Chat Icon Scale Animation & Page Hiding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide the chat floating action button on specific pages and replace the slide animation with a smooth scale animation using Svelte transitions.

**Architecture:** Move visibility/animation control to +layout.svelte where routing decisions belong. Define which pages hide the FAB at the layout level. ChatPanel becomes a simple "dumb" component that just renders the FAB with Svelte transitions when instructed. Replace CSS keyframe animation with Svelte's `transition:scale` directive.

**Tech Stack:** Svelte 5 (runes, transitions), regex for route matching

---

## File Structure

```
frontend/src/routes/
  +layout.svelte               # MODIFY - add route hiding logic + conditional render
frontend/src/lib/
  components/
    ChatPanel.svelte           # MODIFY - remove path logic, use Svelte transition
```

---

### Task 1: Update +layout.svelte to add route visibility logic

**Files:**
- Modify: `frontend/src/routes/+layout.svelte` (around line 200)

- [ ] **Step 1: Add helper function for route checking**

In the `<script>` block at the top of `+layout.svelte`, add this function after the imports:

```typescript
function shouldHideChatIcon(path: string): boolean {
  return /^\/protocols\/[^/]+$/.test(path) ||
         /^\/runs\/[^/]+$/.test(path) ||
         /^\/library\/[^/]+$/.test(path) ||
         path.startsWith('/chat') ||
         path === '/export';
}
```

- [ ] **Step 2: Add derived state to track visibility**

In the `<script>` block, add this derived state (alongside other $derived declarations):

```typescript
const shouldShowChat = $derived(!shouldHideChatIcon($page.url.pathname));
```

- [ ] **Step 3: Update the ChatPanel conditional render**

Find the ChatPanel component render (currently around line 200) and update it:

**Old code:**
```svelte
<ChatPanel currentPath={$page.url.pathname} />
```

**New code:**
```svelte
{#if shouldShowChat}
    <ChatPanel />
{/if}
```

**Explanation:** Remove the `currentPath` prop (ChatPanel no longer needs it) and wrap in a conditional that uses the derived state.

- [ ] **Step 4: Verify syntax**

Run type checker:

```bash
cd frontend
npm run check
```

Expected output: No TypeScript errors or warnings

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/+layout.svelte
git commit -m "feat: move chat icon visibility logic to layout level"
```

---

### Task 2: Update ChatPanel.svelte to remove path logic and add Svelte transition

**Files:**
- Modify: `frontend/src/lib/components/ChatPanel.svelte`

- [ ] **Step 1: Remove the currentPath prop**

Remove this line from the top of the `<script>` block:

```typescript
let { currentPath = '' } = $props();
```

- [ ] **Step 2: Remove the isOnChatPage derived state**

Delete this line from the derived state section:

```typescript
const isOnChatPage = $derived(currentPath.startsWith('/chat'));
```

- [ ] **Step 3: Update the handleGlobalKeydown function**

Find the `handleGlobalKeydown` function and simplify it:

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
        togglePanel();
    }
}
```

**Explanation:** Remove the `if (!isOnChatPage)` guard since the layout now controls whether ChatPanel renders at all.

- [ ] **Step 4: Update the FAB button with Svelte transition**

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
{#if panelState === 'collapsed'}
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
- Added `transition:scale={{ duration: 200, start: 0 }}`
- Removed `class` opacity styling (`{isOnChatPage ? 'opacity-40' : ''}`)
- Removed `disabled={isOnChatPage}` attribute
- Removed the guard in `onclick={() => !isOnChatPage && openPanel()}` to just `onclick={() => openPanel()}`

- [ ] **Step 5: Remove the old CSS animation**

In the `<style>` block, delete the `chat-fab-in` keyframe and `.chat-fab` rule:

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

- [ ] **Step 6: Verify syntax**

```bash
cd frontend
npm run check
```

Expected output: No TypeScript errors or warnings

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/components/ChatPanel.svelte
git commit -m "feat: remove path logic from ChatPanel, add Svelte scale transition"
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

- [ ] **Step 2: Navigate to /protocols/[id] and verify icon hides with scale animation**

1. Open `http://localhost:5173/` first and verify the chat FAB is visible
2. Navigate to `http://localhost:5173/protocols/123` (use any numeric ID)
3. Verify the chat FAB scales out smoothly (animation should be visible)
4. Verify the chat FAB is completely gone on this page
5. Navigate back to `/` 
6. Verify the chat FAB scales in smoothly (0 → 1)
7. Verify no console errors

- [ ] **Step 3: Navigate to /runs/[id] and verify icon hides**

1. Go to `http://localhost:5173/runs/456`
2. Verify the FAB scales out and is not visible
3. Navigate back to `/`
4. Verify the FAB scales in

- [ ] **Step 4: Navigate to /chat and verify icon hides**

1. Go to `http://localhost:5173/chat`
2. Verify the FAB is not visible
3. Navigate to another page (e.g., `/`)
4. Verify the FAB scales in

- [ ] **Step 5: Navigate to /library/[id] and verify icon hides**

1. Go to `http://localhost:5173/library/789`
2. Verify the FAB scales out and is not visible
3. Navigate back to `/`
4. Verify the FAB scales in

- [ ] **Step 6: Navigate to /export and verify icon hides**

1. Go to `http://localhost:5173/export`
2. Verify the FAB is not visible
3. Navigate back to `/`
4. Verify the FAB scales in

- [ ] **Step 7: Test keyboard shortcut on hidden pages**

1. Navigate to `/chat`
2. Press Cmd+J (Mac) or Ctrl+J (Windows/Linux)
3. Verify nothing happens (chat panel should NOT open since ChatPanel is not rendered)
4. Navigate to a visible page (e.g., `/`)
5. Press Cmd+J / Ctrl+J
6. Verify the chat panel opens

- [ ] **Step 8: Test FAB on visible pages**

1. Navigate to `/` (homepage)
2. Verify the chat FAB is visible
3. Click it and verify the chat panel opens
4. Close the panel (verify FAB scales out as panel closes)
5. Verify the FAB scales back in
6. Click FAB again and verify panel opens

- [ ] **Step 9: Mark as complete**

Testing complete. All pages tested, scale animations verified in both directions, no errors.

---

## Self-Review Checklist

**Spec Coverage:**
- ✓ Route visibility logic in +layout.svelte (where routing decisions belong)
- ✓ Conditional rendering of ChatPanel (scales out/in when navigating)
- ✓ Svelte transition added with scale animation
- ✓ Old CSS keyframe removed
- ✓ All 5 routes hidden: `/protocols/[id]`, `/runs/[id]`, `/chat`, `/library/[id]`, `/export`
- ✓ ChatPanel is "dumb" component (no path logic)
- ✓ Browser testing on all pages

**Placeholder Scan:**
- ✓ All code blocks are complete and ready to copy-paste
- ✓ All commands include exact expected output
- ✓ No "TBD", "TODO", or incomplete instructions

**Type Consistency:**
- ✓ `shouldShowChat` derived state correctly inverts `shouldHideChatIcon()` result
- ✓ `transition:scale` parameters consistent
- ✓ All regex patterns match the spec's route patterns
- ✓ No `currentPath` prop passed to ChatPanel anymore

**Architectural Soundness:**
- ✓ Route visibility logic in layout (single responsibility)
- ✓ ChatPanel simplified (no path checking)
- ✓ Animation handled by Svelte (idiomatic)
- ✓ No utility file needed (logic stays in layout)
