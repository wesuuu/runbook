---
paths:
  - "frontend/src/lib/components/**"
  - "frontend/src/pages/**"
  - "frontend/src/routes/**"
---

# Frontend Component Patterns

## Two Component Categories

### UI Components (`components/ui/`)

shadcn-svelte pattern. Each in its own folder with barrel `index.ts`:

```
components/ui/button/
  button.svelte      # Implementation
  index.ts           # Re-exports: Root as Button, buttonVariants, type Props
```

- Use `tailwind-variants` (`tv()`) for variant styling
- Accept `ref = $bindable(null)` for forwarding
- Compose from `bits-ui` primitives
- Use `cn()` utility for className merging (clsx + tailwind-merge)

### Feature Components (`components/`)

Named by feature, not by UI role:

```svelte
<script lang="ts">
interface Props {
    node: Node | null;
    allNodes: Node[];
    onApply: (nodeId: string, params: Record<string, any>) => void;
}
let { node, allNodes, onApply }: Props = $props();
</script>
```

- Props via `interface Props` + `$props()` destructuring
- Callbacks prefixed with `on`: `onApply`, `onClose`, `onSaveAsNew`
- Import store getters and derive: `const user = $derived(getUser());`

## Page Component Pattern

```svelte
<script lang="ts">
let items = $state<Item[]>([]);
let loading = $state(true);
let error = $state<string | null>(null);

async function loadItems() {
    loading = true;
    try {
        const res = await api.get('/items', { schema: ItemListSchema });
        items = Array.isArray(res) ? res : [];
    } catch (e: unknown) {
        error = e instanceof Error ? e.message : 'An error occurred';
    } finally {
        loading = false;
    }
}
onMount(loadItems);
</script>
```

## Tab-Based Pages

Use URL search params for tab state:

```typescript
type TabName = "protocols" | "experiments" | "runs";
const activeTab: TabName = $derived.by(() => {
    const t = $page.url.searchParams.get("tab");
    return validTabs.includes(t as TabName) ? (t as TabName) : "protocols";
});

function setTab(tab: TabName) {
    goto(`?tab=${tab}`, { replaceState: false, keepFocus: true, noScroll: true });
}
```

## Styling

- Tailwind utilities for layout
- Scoped `<style>` blocks for component-specific CSS
- CSS custom properties for theming (`--cat-color`, `--lane-color`)
- Dark mode via CSS classes
- `cn()` for conditional/merged classnames

## Interactive Elements

- **Pointer cursor**: All clickable elements (links, buttons, cards, rows, avatars, icons acting as actions) must use `cursor-pointer`.
- **Hover feedback**: Clickable elements need visible hover states — darken with `hover:brightness-90` or `hover:bg-muted`, or scale up slightly with `hover:scale-105` (appropriate for avatars, icons, cards).
- **Transitions on hover**: Always pair hover effects with a smooth transition: `transition-all duration-150` or similar.

## Page & Element Transitions

- **Page navigation**: Use Svelte transitions on page-level content so route changes feel smooth, not jarring. Apply `fade` or `fly` from `svelte/transition` on the top-level wrapper of each page.
- **Element creation/destruction**: When elements enter or leave the DOM (lists, cards, modals, toasts), apply Svelte transitions (`fade`, `fly`, `slide`, `scale`). Use `animate:flip` for reordering lists.
- **Loading states**: Transition between loading skeletons and loaded content with `fade` to avoid hard pops.
