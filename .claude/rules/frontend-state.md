---
paths:
  - "frontend/src/lib/auth.svelte.ts"
  - "frontend/src/lib/chat-store.svelte.ts"
  - "frontend/src/lib/*.svelte.ts"
---

# Frontend State Management (Svelte 5)

## The Pattern: Module-Level Runes in `.svelte.ts` Files

Global state uses module-level `$state` in `.svelte.ts` files. NOT SvelteKit stores. NOT context.

```typescript
// auth.svelte.ts
let user = $state<User | null>(null);
let token = $state<string | null>(localStorage.getItem('auth_token'));

// Getters -- components subscribe via $derived(getUser())
export function getUser(): User | null { return user; }
export function isAuthenticated(): boolean { return token !== null && user !== null; }

// Actions -- mutations through exported functions
export async function login(email: string, password: string): Promise<void> { ... }
export function logout(): void { ... }
```

## Key Rules

- `.svelte.ts` extension is required for files using `$state`, `$derived`, `$effect`
- State is module-level `let` with `$state()` -- survives client-side navigation
- **Getters** are plain functions returning state -- components use `$derived(getter())`
- **Actions** are exported async/sync functions that mutate state
- No classes, no store objects -- just functions and module-scoped variables
- Avoid circular imports: use lazy `import()` when stores reference each other (see `logout()` calling `resetChat()`)

## Component Consumption

```svelte
<script lang="ts">
import { getUser, isAuthenticated } from '$lib/auth.svelte';

const user = $derived(getUser());
const authed = $derived(isAuthenticated());
</script>
```

## Optimistic Updates (Chat Store Pattern)

```typescript
// 1. Add temp message immediately
activeSession.messages = [...activeSession.messages, tempUserMsg];
await tick();
scrollFn?.();

// 2. Make API call
const res = await api.post(...);

// 3. Replace temp with real
activeSession.messages = [
    ...activeSession.messages.filter(m => m.id !== tempUserMsg.id),
    res.user_message, res.assistant_message,
];
```

## When to Use Context vs Module State

- **Module state** (`.svelte.ts`): app-wide singletons (auth, chat, connectivity)
- **Svelte context** (`setContext`/`getContext`): parent-to-deeply-nested-child data within a component tree (e.g., ProtocolEditor passing orientation to UnitOpNode)
- **Component props**: direct parent-child communication
