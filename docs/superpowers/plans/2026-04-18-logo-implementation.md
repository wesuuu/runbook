# Logo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all hardcoded "B" and "R" badge logos with the new Batchrite logo image throughout the frontend, plus set favicon.

**Architecture:** Create a reusable Logo component that accepts a size prop, then use it to replace inline badge markup in four locations (header, loading state, login page, mobile nav). Add favicon link to app.html.

**Tech Stack:** Svelte 5, Vite, TailwindCSS

---

## Task 1: Create Logo Component

**Files:**
- Create: `frontend/src/lib/components/Logo.svelte`

- [ ] **Step 1: Create Logo.svelte component file**

Create `frontend/src/lib/components/Logo.svelte`:

```svelte
<script lang="ts">
    interface Props {
        size?: 'sm' | 'md' | 'lg';
        class?: string;
    }

    let { size = 'md', class: cls = '' } = $props();

    const sizeMap = {
        sm: 'w-7 h-7',      // 28px
        md: 'w-8 h-8',      // 32px
        lg: 'w-12 h-12',    // 48px
    };
</script>

<img
    src="/logo.png"
    alt="Batchrite"
    class="{sizeMap[size]} object-cover {cls}"
/>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/components/Logo.svelte
git commit -m "feat: create Logo component"
```

---

## Task 2: Update Header Navigation Logo

**Files:**
- Modify: `frontend/src/routes/+layout.svelte:129-150`

- [ ] **Step 1: Import Logo component at top of +layout.svelte**

At the top of the `<script>` block (after other imports, around line 22), add:

```typescript
import Logo from '$lib/components/Logo.svelte';
```

- [ ] **Step 2: Replace header badge with Logo component**

Find the logo badge section in the header (lines 142-149):

```svelte
<a href="/" class="flex items-center gap-2.5 group">
    <div
        class="w-7 h-7 bg-primary rounded-md flex items-center justify-center shadow-sm shadow-primary/20 group-hover:shadow-md group-hover:shadow-primary/30 transition-all"
    >
        <span class="font-mono text-sm font-medium text-primary-foreground leading-none">B</span>
    </div>
    <span class="text-[15px] font-semibold text-foreground tracking-tight">Batchrite</span>
</a>
```

Replace the inner `<div>` containing the "B" span with just the Logo component:

```svelte
<a href="/" class="flex items-center gap-2.5 group">
    <div class="shadow-sm shadow-primary/20 group-hover:shadow-md group-hover:shadow-primary/30 transition-all rounded-md">
        <Logo size="md" />
    </div>
    <span class="text-[15px] font-semibold text-foreground tracking-tight">Batchrite</span>
</a>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/+layout.svelte
git commit -m "feat: replace header logo with Logo component"
```

---

## Task 3: Update Loading State Logo

**Files:**
- Modify: `frontend/src/routes/+layout.svelte:107-119`

- [ ] **Step 1: Replace loading state badge with Logo component**

Find the loading state section (lines 107-118):

```svelte
{#if !isInitialized()}
    <div class="min-h-screen flex items-center justify-center bg-background">
        <div class="flex flex-col items-center gap-4">
            <div class="relative">
                <div class="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                    <span class="font-mono text-lg font-medium text-primary">R</span>
                </div>
                <div class="absolute inset-0 w-10 h-10 rounded-xl border-2 border-primary/20 animate-ping"></div>
            </div>
            <p class="text-sm text-muted-foreground tracking-wide">Loading...</p>
        </div>
    </div>
```

Replace the inner divs with the Logo component (remove the pulsing border):

```svelte
{#if !isInitialized()}
    <div class="min-h-screen flex items-center justify-center bg-background">
        <div class="flex flex-col items-center gap-4">
            <div class="relative">
                <Logo size="md" />
            </div>
            <p class="text-sm text-muted-foreground tracking-wide">Loading...</p>
        </div>
    </div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/routes/+layout.svelte
git commit -m "feat: replace loading state logo with Logo component"
```

---

## Task 4: Update Login Page Logo

**Files:**
- Modify: `frontend/src/routes/login/+page.svelte:1-50`

- [ ] **Step 1: Import Logo component**

At the top of the `<script>` block (after other imports, around line 10), add:

```typescript
import Logo from '$lib/components/Logo.svelte';
```

- [ ] **Step 2: Replace login badge with Logo component**

Find the logo section (lines 39-47):

```svelte
<div class="flex flex-col items-center mb-10">
    <div
        class="w-12 h-12 bg-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary/20 mb-4"
    >
        <span class="font-mono text-xl font-medium text-primary-foreground leading-none">B</span>
    </div>
    <h1 class="text-2xl font-bold text-foreground tracking-tight">Batchrite</h1>
    <p class="text-sm text-muted-foreground mt-1.5">Laboratory Execution System</p>
</div>
```

Replace the inner `<div>` containing the "B" with the Logo component:

```svelte
<div class="flex flex-col items-center mb-10">
    <div class="shadow-lg shadow-primary/20 mb-4 rounded-xl">
        <Logo size="lg" />
    </div>
    <h1 class="text-2xl font-bold text-foreground tracking-tight">Batchrite</h1>
    <p class="text-sm text-muted-foreground mt-1.5">Laboratory Execution System</p>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/login/+page.svelte
git commit -m "feat: replace login page logo with Logo component"
```

---

## Task 5: Update Mobile Navigation Logo

**Files:**
- Modify: `frontend/src/lib/components/MobileNav.svelte:1-50`

- [ ] **Step 1: Import Logo component**

At the top of the `<script>` block (after other imports, around line 3), add:

```typescript
import Logo from '$lib/components/Logo.svelte';
```

- [ ] **Step 2: Replace mobile nav badge and text**

Find the mobile nav header section (lines 42-48):

```svelte
<div class="flex items-center justify-between px-5 py-4 border-b border-border">
    <a href="/" class="flex items-center gap-2.5" onclick={close}>
        <div class="w-7 h-7 bg-primary rounded-md flex items-center justify-center shadow-sm shadow-primary/20">
            <span class="font-mono text-sm font-medium text-primary-foreground leading-none">R</span>
        </div>
        <span class="text-[15px] font-semibold text-foreground tracking-tight">Runbook</span>
    </a>
```

Replace the badge div and "Runbook" text:

```svelte
<div class="flex items-center justify-between px-5 py-4 border-b border-border">
    <a href="/" class="flex items-center gap-2.5" onclick={close}>
        <div class="shadow-sm shadow-primary/20 rounded-md">
            <Logo size="sm" />
        </div>
        <span class="text-[15px] font-semibold text-foreground tracking-tight">Batchrite</span>
    </a>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/MobileNav.svelte
git commit -m "feat: replace mobile nav logo with Logo component and fix text to Batchrite"
```

---

## Task 6: Add Favicon

**Files:**
- Modify: `frontend/src/app.html:1-20`

- [ ] **Step 1: Add favicon link to app.html**

Open `frontend/src/app.html` and locate the `<head>` section. Find the line with `<meta charset="utf-8" />` (usually around line 5-6).

After the meta tags and before any other `<link>` tags, add:

```html
<link rel="icon" type="image/png" href="/logo.png" />
```

The head section should look similar to:

```html
<head>
    <meta charset="utf-8" />
    <link rel="icon" type="image/png" href="/logo.png" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    %sveltekit.head%
</head>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app.html
git commit -m "feat: add favicon using logo.png"
```

---

## Task 7: Manual Testing

**Files:**
- No files modified

- [ ] **Step 1: Start dev servers**

```bash
cd frontend && npm run dev
# In another terminal:
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010
```

Wait for both servers to start (frontend :5173, backend :8010).

- [ ] **Step 2: Test loading state**

Open browser to `http://localhost:5173`. You should see the logo (not "R" badge) centered on the loading screen while the app initializes. Verify the logo displays correctly and no pulsing border appears.

- [ ] **Step 3: Test header logo**

Once fully loaded, verify the header shows the logo (not "B" badge) next to "Batchrite" text. Test hover effects work (shadow should grow on hover).

- [ ] **Step 4: Test login page**

Navigate to `http://localhost:5173/login` by clicking sign out. Verify the larger logo (not "B" badge) displays above "Batchrite" heading on login page.

- [ ] **Step 5: Test mobile nav**

Resize browser to mobile width (< 768px) and click the hamburger menu. Verify mobile nav shows the logo (not "R" badge) and text says "Batchrite" (not "Runbook").

- [ ] **Step 6: Test favicon**

Check browser tab — favicon should show the logo image (may take a few seconds to load). Hard refresh if needed (Ctrl+Shift+R or Cmd+Shift+R).

- [ ] **Step 7: Verify all sizes**

Visually verify the logo displays correctly at all three sizes (sm, md, lg) across the app. Logo should be crisp and not distorted.

---

## Task 8: Final Commit

**Files:**
- No files modified (all changes already committed per-task)

- [ ] **Step 1: Verify all commits**

```bash
git log --oneline -5
```

You should see:
- feat: add favicon using logo.png
- feat: replace mobile nav logo with Logo component and fix text to Batchrite
- feat: replace login page logo with Logo component
- feat: replace header logo with Logo component
- feat: replace loading state logo with Logo component
- feat: create Logo component

- [ ] **Step 2: Verify no uncommitted changes**

```bash
git status
```

Should show "working tree clean" or "nothing to commit".

---

## Notes

- All logo sizes use `object-cover` to maintain aspect ratio
- Existing hover effects and shadows on parent divs are preserved
- Logo component is simple and reusable for future branding updates
- The logo.png file (357x320px) is already in `frontend/src/assets/`
- No changes to TailwindCSS config or component styling needed
