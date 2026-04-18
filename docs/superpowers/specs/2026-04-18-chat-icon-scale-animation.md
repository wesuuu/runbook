# Chat Icon Scale Animation & Page Hiding

**Date:** 2026-04-18  
**Task:** F-0074  
**Scope:** Frontend

## Overview

Hide the chat floating action button (FAB) on specific pages and replace the slide animation with a smooth scale animation using Svelte transitions.

## Current Behavior

- Chat icon visible on all pages except `/chat`
- Uses CSS keyframe animation with `translateY(12px)` slide effect
- Icon is disabled and faded (opacity-40) on the chat page

## Desired Behavior

- Hide the chat icon completely on: `/protocols/[id]`, `/runs/[id]`, `/chat`, `/library/[id]`, `/export`
- Icon animates in/out with smooth scale transition (0 → 1) instead of slide
- Animation runs automatically when navigating between hidden and visible pages

## Implementation Approach

### 1. Route Matching

Create a derived state that checks if the current path matches any hidden routes:

```typescript
const shouldHideChat = $derived.by(() => {
  const path = currentPath;
  return /^\/protocols\/[^/]+$/.test(path) ||
         /^\/runs\/[^/]+$/.test(path) ||
         /^\/library\/[^/]+$/.test(path) ||
         path.startsWith('/chat') ||
         path === '/export';
});
```

This regex-based approach ensures dynamic routes like `/protocols/123` match, but `/protocols` alone does not.

### 2. Conditional Rendering & Animation

Update the FAB button block to use the new derived state and Svelte transition:

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
    {/* SVG icon */}
  </Button>
{/if}
```

**Changes:**
- Remove `isOnChatPage ? 'opacity-40' : ''` class (button no longer renders on hidden pages)
- Remove `disabled={isOnChatPage}` attribute (conditional rendering replaces it)
- Add `transition:scale={{ duration: 200, start: 0 }}` for smooth scale animation
- Remove `onclick={() => !isOnChatPage && openPanel()}` guard logic (condition now in `{#if}`)

### 3. CSS Cleanup

Remove the `chat-fab-in` keyframe animation entirely—Svelte's transition directive handles animation:

```css
/* DELETE: @keyframes chat-fab-in { ... } */
/* DELETE: .chat-fab { animation: ... } */
```

Keep the `chat-panel-in` keyframe for the panel itself (unchanged).

## Acceptance Criteria

- [x] Chat icon is not rendered on `/protocols/[id]`, `/runs/[id]`, `/chat`, `/library/[id]`, `/export`
- [x] Icon animates with scale (0 → 1) when appearing
- [x] Icon animates with scale (1 → 0) when disappearing
- [x] Animation is smooth (~200ms) using Svelte transitions
- [x] No custom CSS keyframes needed

## Testing Checklist

1. Navigate to each hidden route and verify icon disappears with scale-out animation
2. Navigate away from hidden routes and verify icon appears with scale-in animation
3. Click FAB on visible pages to open chat panel
4. Check that panel opens correctly
5. Verify no console errors during navigation
6. Test on both desktop and mobile viewports

## Files Affected

- `frontend/src/lib/components/ChatPanel.svelte` (lines 33–101, 300–309)

## Notes

- Svelte transitions are declarative and handle enter/exit animations automatically
- No JS-side animation management needed
- Animation timing of 200ms matches the original CSS animation duration
- The `start: 0` parameter ensures scale starts from 0 on entry (not 0.5 or other default)
