# User-Selectable Themes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users pick from four named themes (Lab Glass [default], Blueprint, Apothecary, Instrument), persisted per-user. Replace the current "warm cream" palette so Batchrite stops looking like an Anthropic-clone AI app.

**Architecture:** Tailwind v4 `@theme` block points at intermediate CSS variables (`--bg`, `--primary`, etc.) that are redefined per `[data-theme="..."]` selector. A `data-theme` attribute on `<html>` controls which palette is active. Persistence rides on the existing `User.preferences` JSONB and the existing `PUT /auth/me/preferences` endpoint — no new column, no migration. localStorage is a write-through cache for instant boot (anti-FOUC) before the user record arrives from the server.

**Tech Stack:** Tailwind v4 (`@theme` + CSS variables), Svelte 5 runes, FastAPI/Pydantic, existing JSONB preferences.

---

## File Structure

**Backend (no migration):**
- Modify: `backend/app/schemas/auth.py:50-52` — add `theme` to `PreferencesUpdate`
- Modify: `backend/app/api/endpoints/auth.py:694-712` — validate + persist theme
- Modify: `backend/tests/integration/test_auth_api.py` — add theme persistence test

**Frontend:**
- Modify: `frontend/src/app.css` — refactor to indirection vars; 4 theme blocks
- Modify: `frontend/src/app.html` — inline anti-FOUC boot script
- Create: `frontend/src/lib/theme.svelte.ts` — theme constants, `getTheme()`, `setTheme()`, `applyTheme()`
- Create: `frontend/src/lib/theme.test.ts` — vitest unit tests
- Modify: `frontend/src/lib/auth.svelte.ts` — sync theme from server preferences after `refreshUser()`
- Create: `frontend/src/lib/components/settings/AppearanceTab.svelte` — radio-card picker w/ mini live previews
- Modify: `frontend/src/routes/settings/+page.svelte` — add `appearance` tab

**Audit & cleanup:**
- Sweep `frontend/src/` for hardcoded light-mode colors that break under `data-theme="instrument"`. Replace with tokens.

---

## Task 1: Backend — accept and validate `theme` in preferences

**Files:**
- Modify: `backend/app/schemas/auth.py:50-52`
- Modify: `backend/app/api/endpoints/auth.py:694-712`
- Test: `backend/tests/integration/test_auth_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_auth_api.py`:

```python
@pytest.mark.asyncio
async def test_update_preferences_persists_theme(
    auth_client: AsyncClient, test_user: User, db_session: AsyncSession
):
    res = await auth_client.put(
        "/auth/me/preferences", json={"theme": "blueprint"}
    )
    assert res.status_code == 200
    assert res.json()["preferences"]["theme"] == "blueprint"

    await db_session.refresh(test_user)
    assert test_user.preferences.get("theme") == "blueprint"


@pytest.mark.asyncio
async def test_update_preferences_rejects_unknown_theme(auth_client: AsyncClient):
    res = await auth_client.put(
        "/auth/me/preferences", json={"theme": "nope"}
    )
    assert res.status_code == 400
    assert "theme" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_preferences_does_not_clobber_other_keys(
    auth_client: AsyncClient, test_user: User, db_session: AsyncSession
):
    await auth_client.put(
        "/auth/me/preferences", json={"font_size": "large"}
    )
    await auth_client.put(
        "/auth/me/preferences", json={"theme": "instrument"}
    )
    await db_session.refresh(test_user)
    assert test_user.preferences.get("font_size") == "large"
    assert test_user.preferences.get("theme") == "instrument"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/test_auth_api.py -k "theme" -v
```
Expected: 3 FAILs — `theme` field unknown / not persisted.

- [ ] **Step 3: Add `theme` field to `PreferencesUpdate`**

Edit `backend/app/schemas/auth.py`. Replace the `PreferencesUpdate` class:

```python
class PreferencesUpdate(BaseModel):
    font_size: Optional[str] = None    # "small" | "medium" | "large"
    density: Optional[str] = None      # "compact" | "comfortable"
    theme: Optional[str] = None        # "lab-glass" | "blueprint" | "apothecary" | "instrument"
```

- [ ] **Step 4: Validate + persist `theme` in endpoint**

Edit `backend/app/api/endpoints/auth.py`, inside `update_preferences` (around line 700). After the existing density block, before `user.preferences = prefs`, add:

```python
    if body.theme is not None:
        if body.theme not in ("lab-glass", "blueprint", "apothecary", "instrument"):
            raise HTTPException(400, "theme must be lab-glass, blueprint, apothecary, or instrument")
        prefs["theme"] = body.theme
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/integration/test_auth_api.py -k "theme" -v
```
Expected: 3 PASS.

- [ ] **Step 6: Run full auth tests to confirm nothing broke**

```bash
pytest tests/integration/test_auth_api.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/auth.py backend/app/api/endpoints/auth.py backend/tests/integration/test_auth_api.py
git commit -m "feat(themes): accept and validate theme in user preferences"
```

---

## Task 2: CSS — indirection variables and four theme palettes

**Files:**
- Modify: `frontend/src/app.css`

- [ ] **Step 1: Replace `app.css` content**

The whole file is short — overwrite it. Note: existing utility classes (`grain`, `dot-grid`, `card-warm`, `accent-line`, `nav-active`, `status-pulse`) are preserved but converted to use tokens.

Write to `frontend/src/app.css`:

```css
@import "tailwindcss";
@plugin "@tailwindcss/typography";

/* Safelist tailwind-variants runtime classes (Tailwind v4 scanner doesn't see tv() configs). */
@source inline("bg-destructive bg-destructive/90 bg-destructive/60 bg-primary bg-primary/90 bg-secondary bg-secondary/80 bg-accent bg-accent/50 bg-accent/90 bg-background bg-input/30 bg-input/50 min-w-[420px] hover:bg-teal-600 hover:text-white hover:border-teal-600 hover:bg-destructive/90 hover:bg-accent/90 hover:bg-emerald-700 bg-emerald-600");

/* ──────────────────────────────────────────────────────────
   Tailwind utilities resolve against these stable token names.
   Each [data-theme] block (below) redefines the underlying
   --bg / --primary / etc. variables to swap palettes at runtime.
   ────────────────────────────────────────────────────────── */
@theme {
    --color-primary: var(--primary);
    --color-primary-foreground: var(--primary-fg);

    --color-background: var(--bg);
    --color-foreground: var(--fg);

    --color-card: var(--card);
    --color-card-foreground: var(--card-fg);

    --color-popover: var(--card);
    --color-popover-foreground: var(--card-fg);

    --color-secondary: var(--muted);
    --color-secondary-foreground: var(--fg);

    --color-muted: var(--muted);
    --color-muted-foreground: var(--muted-fg);

    --color-accent: var(--accent);
    --color-accent-foreground: var(--accent-fg);

    --color-destructive: var(--destructive);
    --color-destructive-foreground: var(--primary-fg);

    --color-border: var(--border);
    --color-input: var(--border);
    --color-ring: var(--ring);

    --radius: 0.625rem;
    --radius-lg: 0.625rem;
    --radius-md: 0.375rem;
    --radius-sm: 0.125rem;

    --font-sans: 'DM Sans', system-ui, sans-serif;
    --font-mono: 'DM Mono', ui-monospace, monospace;
}

/* ──────────────────────────────────────────────────────────
   Theme palettes — :root falls back to lab-glass.
   ────────────────────────────────────────────────────────── */
:root,
[data-theme="lab-glass"] {
    --bg:           hsl(200 25% 97%);
    --fg:           hsl(215 40% 12%);
    --card:         hsl(0 0% 100%);
    --card-fg:      hsl(215 40% 12%);
    --muted:        hsl(205 25% 94%);
    --muted-fg:     hsl(215 15% 42%);
    --primary:      hsl(195 85% 22%);
    --primary-fg:   hsl(195 30% 98%);
    --accent:       hsl(155 70% 38%);
    --accent-fg:    hsl(155 30% 98%);
    --destructive:  hsl(355 75% 50%);
    --border:       hsl(205 22% 87%);
    --ring:         hsl(195 85% 22%);
    --grid-dot:     hsl(205 30% 70% / 0.25);
}

[data-theme="blueprint"] {
    --bg:           hsl(210 32% 96%);
    --fg:           hsl(218 55% 14%);
    --card:         hsl(210 45% 99%);
    --card-fg:      hsl(218 55% 14%);
    --muted:        hsl(210 28% 92%);
    --muted-fg:     hsl(218 18% 42%);
    --primary:      hsl(218 70% 22%);
    --primary-fg:   hsl(210 40% 98%);
    --accent:       hsl(35 95% 55%);
    --accent-fg:    hsl(35 80% 12%);
    --destructive:  hsl(0 72% 50%);
    --border:       hsl(210 28% 84%);
    --ring:         hsl(218 70% 30%);
    --grid-dot:     hsl(218 50% 45% / 0.22);
}

[data-theme="apothecary"] {
    --bg:           hsl(60 20% 96%);
    --fg:           hsl(150 28% 12%);
    --card:         hsl(45 28% 98%);
    --card-fg:      hsl(150 28% 12%);
    --muted:        hsl(60 14% 92%);
    --muted-fg:     hsl(150 12% 38%);
    --primary:      hsl(155 45% 20%);
    --primary-fg:   hsl(60 25% 97%);
    --accent:       hsl(15 70% 45%);
    --accent-fg:    hsl(60 25% 97%);
    --destructive:  hsl(8 70% 42%);
    --border:       hsl(60 14% 84%);
    --ring:         hsl(155 45% 25%);
    --grid-dot:     hsl(150 25% 50% / 0.22);
}

[data-theme="instrument"] {
    --bg:           hsl(220 18% 9%);
    --fg:           hsl(210 20% 92%);
    --card:         hsl(220 15% 13%);
    --card-fg:      hsl(210 20% 92%);
    --muted:        hsl(220 14% 17%);
    --muted-fg:     hsl(210 12% 62%);
    --primary:      hsl(165 75% 50%);
    --primary-fg:   hsl(165 80% 8%);
    --accent:       hsl(40 95% 60%);
    --accent-fg:    hsl(40 80% 10%);
    --destructive:  hsl(355 75% 60%);
    --border:       hsl(220 12% 22%);
    --ring:         hsl(165 75% 50%);
    --grid-dot:     hsl(165 40% 60% / 0.18);
}

@layer base {
    * { @apply border-border; }
    a[href] { cursor: pointer; }
    body {
        @apply bg-background text-foreground font-sans antialiased;
        font-feature-settings: "cv11", "ss01";
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
}

/* ── Grain overlay (preserved) ── */
.grain::before {
    content: '';
    position: fixed;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    opacity: 0.025;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    background-repeat: repeat;
    background-size: 256px 256px;
}

/* ── Dot grid (themed) ── */
.dot-grid {
    background-image: radial-gradient(circle, var(--grid-dot) 1px, transparent 1px);
    background-size: 24px 24px;
}

/* ── Themed card ── */
.card-warm {
    background: var(--card);
    border: 1px solid var(--border);
    box-shadow:
        0 1px 2px hsl(0 0% 0% / 0.06),
        0 4px 12px hsl(0 0% 0% / 0.04);
}

/* ── Accent underline ── */
.accent-line {
    position: relative;
}
.accent-line::after {
    content: '';
    position: absolute;
    bottom: -2px;
    left: 0;
    width: 100%;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), transparent);
}

/* ── Status pulse ── */
.status-pulse {
    animation: pulse-glow 2.5s ease-in-out infinite;
}
@keyframes pulse-glow {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.5; }
}

/* ── Active nav link ── */
.nav-active {
    color: var(--primary);
    font-weight: 600;
    position: relative;
}
.nav-active::after {
    content: '';
    position: absolute;
    bottom: -12px;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--accent);
    border-radius: 1px;
}
```

- [ ] **Step 2: Run frontend type-check + build smoke test**

```bash
cd frontend && npm run check
```
Expected: PASS (no svelte-check errors).

```bash
npm run build
```
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app.css
git commit -m "feat(themes): refactor app.css to themed CSS variables with 4 palettes"
```

---

## Task 3: Anti-FOUC inline boot script

**Files:**
- Modify: `frontend/src/app.html`

- [ ] **Step 1: Read current app.html**

```bash
cat frontend/src/app.html
```

- [ ] **Step 2: Add inline script in `<head>` before `%sveltekit.head%`**

Insert this script tag immediately before `%sveltekit.head%` so it runs before any rendered markup. Use this exact snippet (it's defensive against missing localStorage in SSR/iframe contexts):

```html
<script>
    (function () {
        try {
            var t = localStorage.getItem('batchrite.theme');
            var allowed = ['lab-glass','blueprint','apothecary','instrument'];
            document.documentElement.dataset.theme = allowed.indexOf(t) >= 0 ? t : 'lab-glass';
        } catch (e) {
            document.documentElement.dataset.theme = 'lab-glass';
        }
    })();
</script>
```

- [ ] **Step 3: Verify in browser**

Start dev servers (worktree ports per CLAUDE.md):
```bash
# backend
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010 &
# frontend
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183
```

Open http://localhost:5183/ , inspect `<html>`. Expected: `data-theme="lab-glass"` set before any content paints. View source — the inline script appears before SvelteKit's hydration markers.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app.html
git commit -m "feat(themes): inline boot script applies persisted theme pre-hydration"
```

---

## Task 4: Theme module (`theme.svelte.ts`) with tests

**Files:**
- Create: `frontend/src/lib/theme.svelte.ts`
- Create: `frontend/src/lib/theme.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/theme.test.ts`:

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
    THEMES,
    DEFAULT_THEME,
    isTheme,
    getTheme,
    setTheme,
    applyThemeFromCache,
} from './theme.svelte';

describe('theme', () => {
    beforeEach(() => {
        localStorage.clear();
        document.documentElement.removeAttribute('data-theme');
    });

    it('exposes the four theme ids', () => {
        expect(THEMES).toEqual(['lab-glass', 'blueprint', 'apothecary', 'instrument']);
        expect(DEFAULT_THEME).toBe('lab-glass');
    });

    it('isTheme accepts only known ids', () => {
        expect(isTheme('lab-glass')).toBe(true);
        expect(isTheme('instrument')).toBe(true);
        expect(isTheme('nope')).toBe(false);
        expect(isTheme(null)).toBe(false);
    });

    it('applyThemeFromCache reads localStorage and sets data-theme', () => {
        localStorage.setItem('batchrite.theme', 'apothecary');
        applyThemeFromCache();
        expect(document.documentElement.dataset.theme).toBe('apothecary');
        expect(getTheme()).toBe('apothecary');
    });

    it('applyThemeFromCache falls back to default for invalid value', () => {
        localStorage.setItem('batchrite.theme', 'garbage');
        applyThemeFromCache();
        expect(document.documentElement.dataset.theme).toBe('lab-glass');
        expect(getTheme()).toBe('lab-glass');
    });

    it('setTheme updates DOM, localStorage, and module state', async () => {
        const persistFn = vi.fn().mockResolvedValue(undefined);
        await setTheme('blueprint', persistFn);
        expect(document.documentElement.dataset.theme).toBe('blueprint');
        expect(localStorage.getItem('batchrite.theme')).toBe('blueprint');
        expect(getTheme()).toBe('blueprint');
        expect(persistFn).toHaveBeenCalledWith('blueprint');
    });

    it('setTheme rejects invalid theme ids', async () => {
        await expect(setTheme('nope' as any)).rejects.toThrow();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npm run test -- theme.test.ts
```
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `theme.svelte.ts`**

Create `frontend/src/lib/theme.svelte.ts`:

```typescript
export const THEMES = ['lab-glass', 'blueprint', 'apothecary', 'instrument'] as const;
export type Theme = typeof THEMES[number];
export const DEFAULT_THEME: Theme = 'lab-glass';

const STORAGE_KEY = 'batchrite.theme';

let current = $state<Theme>(DEFAULT_THEME);

export function isTheme(value: unknown): value is Theme {
    return typeof value === 'string' && (THEMES as readonly string[]).includes(value);
}

export function getTheme(): Theme {
    return current;
}

export function applyThemeFromCache(): void {
    let stored: string | null = null;
    try {
        stored = localStorage.getItem(STORAGE_KEY);
    } catch {
        stored = null;
    }
    const next = isTheme(stored) ? stored : DEFAULT_THEME;
    current = next;
    document.documentElement.dataset.theme = next;
}

export async function setTheme(
    next: Theme,
    persist?: (theme: Theme) => Promise<void>,
): Promise<void> {
    if (!isTheme(next)) {
        throw new Error(`Unknown theme: ${next}`);
    }
    current = next;
    document.documentElement.dataset.theme = next;
    try {
        localStorage.setItem(STORAGE_KEY, next);
    } catch {
        // private mode / quota — non-fatal
    }
    if (persist) {
        await persist(next);
    }
}

/** Sync from server preferences (called after refreshUser). Server is source of truth. */
export function syncThemeFromServer(prefs: Record<string, string> | null | undefined): void {
    const serverTheme = prefs?.theme;
    if (isTheme(serverTheme) && serverTheme !== current) {
        current = serverTheme;
        document.documentElement.dataset.theme = serverTheme;
        try { localStorage.setItem(STORAGE_KEY, serverTheme); } catch { /* */ }
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm run test -- theme.test.ts
```
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/theme.svelte.ts frontend/src/lib/theme.test.ts
git commit -m "feat(themes): add theme module with localStorage cache + server sync"
```

---

## Task 5: Sync theme from server on user refresh

**Files:**
- Modify: `frontend/src/lib/auth.svelte.ts`

- [ ] **Step 1: Add import + sync call**

Edit `frontend/src/lib/auth.svelte.ts`. At the top with other imports, add:

```typescript
import { syncThemeFromServer } from '$lib/theme.svelte';
```

Then update `refreshUser()` (currently around line 60). Replace its body with:

```typescript
export async function refreshUser(): Promise<void> {
    if (!token) return;
    try {
        user = await authFetch<User>('GET', '/auth/me');
        cacheAuthData();
        syncThemeFromServer(user?.preferences);
    } catch {
        // ignore — keep existing data (could be offline)
    }
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npm run check
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/auth.svelte.ts
git commit -m "feat(themes): sync theme from server preferences on refreshUser"
```

---

## Task 6: Appearance settings tab

**Files:**
- Create: `frontend/src/lib/components/settings/AppearanceTab.svelte`
- Modify: `frontend/src/routes/settings/+page.svelte`

- [ ] **Step 1: Create the tab component**

Create `frontend/src/lib/components/settings/AppearanceTab.svelte`:

```svelte
<script lang="ts">
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import { refreshUser } from '$lib/auth.svelte';
    import { getTheme, setTheme, type Theme } from '$lib/theme.svelte';
    import {
        Card, CardContent, CardHeader, CardTitle, CardDescription,
    } from '$lib/components/ui/card';

    type ThemeOption = {
        id: Theme;
        title: string;
        blurb: string;
    };

    const OPTIONS: ThemeOption[] = [
        { id: 'lab-glass',  title: 'Lab Glass',  blurb: 'Cold, clinical white-blue. The default.' },
        { id: 'blueprint',  title: 'Blueprint',  blurb: 'Drafted paper-blue with ochre accents.' },
        { id: 'apothecary', title: 'Apothecary', blurb: 'Botanical: parchment, moss, tannin rust.' },
        { id: 'instrument', title: 'Instrument', blurb: 'Dark equipment panel with phosphor accents.' },
    ];

    let selected = $derived<Theme>(getTheme());
    let saving = $state(false);

    async function persist(theme: Theme) {
        await api.put('/auth/me/preferences', { theme });
        await refreshUser();
    }

    async function pick(id: Theme) {
        if (id === selected || saving) return;
        saving = true;
        try {
            await setTheme(id, persist);
            toast.success('Theme updated');
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to save theme');
        } finally {
            saving = false;
        }
    }
</script>

<Card>
    <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>
            Pick the visual theme used across Batchrite. Choices apply to your account on every device.
        </CardDescription>
    </CardHeader>
    <CardContent>
        <div class="grid gap-4 sm:grid-cols-2">
            {#each OPTIONS as opt (opt.id)}
                <button
                    type="button"
                    onclick={() => pick(opt.id)}
                    disabled={saving}
                    aria-pressed={selected === opt.id}
                    class="group text-left rounded-lg border p-4 transition-all duration-150 cursor-pointer
                           hover:border-primary/60 disabled:opacity-60 disabled:cursor-not-allowed
                           {selected === opt.id ? 'border-primary ring-2 ring-primary/30' : 'border-border'}"
                >
                    <!-- Scoped preview swatch using its own [data-theme] -->
                    <div data-theme={opt.id} class="mb-3 rounded-md border border-border overflow-hidden">
                        <div class="bg-background p-3 flex gap-2 items-center">
                            <div class="w-8 h-8 rounded bg-primary"></div>
                            <div class="flex-1">
                                <div class="h-2 w-3/4 rounded bg-foreground/80 mb-1.5"></div>
                                <div class="h-2 w-1/2 rounded bg-muted-foreground/60"></div>
                            </div>
                            <div class="w-3 h-3 rounded-full bg-accent"></div>
                        </div>
                        <div class="bg-card px-3 py-2 border-t border-border flex gap-1.5">
                            <div class="h-1.5 flex-1 rounded bg-muted"></div>
                            <div class="h-1.5 w-6 rounded bg-accent"></div>
                            <div class="h-1.5 w-3 rounded bg-primary"></div>
                        </div>
                    </div>

                    <div class="flex items-center justify-between">
                        <p class="text-sm font-semibold">{opt.title}</p>
                        {#if selected === opt.id}
                            <span class="text-xs font-mono text-primary">SELECTED</span>
                        {/if}
                    </div>
                    <p class="text-xs text-muted-foreground mt-1">{opt.blurb}</p>
                </button>
            {/each}
        </div>
    </CardContent>
</Card>
```

- [ ] **Step 2: Wire the tab into Settings page**

Edit `frontend/src/routes/settings/+page.svelte`:

(a) Add import at top with other settings imports (around line 22):

```typescript
import AppearanceTab from '$lib/components/settings/AppearanceTab.svelte';
```

(b) Update the `TabName` type and `VALID_TABS` (line 29-30):

```typescript
type TabName = 'organization' | 'teams' | 'profile' | 'notifications' | 'ai' | 'templates' | 'billing' | 'appearance';
const VALID_TABS: TabName[] = ['organization', 'teams', 'profile', 'notifications', 'ai', 'templates', 'billing', 'appearance'];
```

(c) Add the Appearance tab button in the tab nav. Insert immediately after the Profile button (around line 674):

```svelte
        <Button
            variant="tab"
            data-active={activeTab === 'appearance'}
            onclick={() => setTab('appearance')}
            class="py-2.5 min-h-11"
        >
            Appearance
        </Button>
```

(d) Add the tab body branch. Insert immediately after the Profile tab block ends (just before the `<!-- Notifications Tab -->` comment, around line 1119):

```svelte
    <!-- Appearance Tab -->
    {:else if activeTab === 'appearance'}
        <AppearanceTab />

```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npm run check
```
Expected: PASS.

- [ ] **Step 4: Manual smoke test in browser**

Login → Settings → Appearance. Click each theme. Confirm:
- The four cards render with mini previews showing each palette
- Clicking a card immediately recolors the whole app
- Hard refresh — theme persists
- Open in a new browser/incognito and login as same user — server preference applies (after a beat)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/settings/AppearanceTab.svelte frontend/src/routes/settings/+page.svelte
git commit -m "feat(themes): Settings → Appearance tab with theme picker and live previews"
```

---

## Task 7: Hardcoded-color audit (Instrument-driven)

**Files:**
- Modify: any file caught by the grep below

- [ ] **Step 1: Switch app to Instrument theme manually**

In a browser console on the running dev app:
```js
document.documentElement.dataset.theme = 'instrument';
localStorage.setItem('batchrite.theme', 'instrument');
```

- [ ] **Step 2: Generate the punch list**

```bash
cd frontend && grep -rn --include='*.svelte' --include='*.ts' \
    -E "bg-(white|gray|slate|zinc|neutral|stone|red|amber|emerald|green|blue)-[0-9]{2,3}\b|\
text-(gray|slate|zinc|neutral|stone)-[0-9]{2,3}\b|\
border-(gray|slate|zinc|neutral|stone)-[0-9]{2,3}\b" src/ | tee /tmp/theme-audit.txt
```

This produces the full list. Each match needs review.

- [ ] **Step 3: Walk every match**

For each line in `/tmp/theme-audit.txt`, decide:
- **Chrome / generic UI** (cards, dividers, text on neutral backgrounds): replace with token (`bg-card`, `bg-muted`, `text-foreground`, `text-muted-foreground`, `border-border`).
- **Semantic state** (success green, error red, warning amber): swap to `bg-success/10 text-success` patterns where present, or keep as-is if visually acceptable on dark — judge per case.
- **Decorative/illustrative** (specific node-graph colors, category badges): leave as-is. These are domain semantics, not chrome.

Example replacements you will encounter:
- `text-slate-800` → `text-foreground`
- `bg-green-100 text-green-800` → keep status badges colored OR swap to `bg-success/15 text-success` if a `--success` token exists (it currently does **not**; either add one or keep the literal). For this pass: keep status badges literal — they're semantic.
- `border-gray-200` → `border-border`
- `bg-white` (on cards/modals) → `bg-card`
- `text-gray-500`, `text-gray-600` → `text-muted-foreground`
- `text-gray-900` → `text-foreground`

Do not blanket-replace — read each call site. Bias toward minimal change.

- [ ] **Step 4: Walk the app in Instrument theme**

With dev servers running and theme set to Instrument, manually visit each major route and visually scan for:
- Bright-white rectangles floating on charcoal (missed `bg-white`)
- Invisible black-on-black text
- Invisible dividers
- Halos around images with baked-in white backgrounds

Routes to walk:
- `/projects` (and project detail)
- `/protocols` and a protocol editor
- `/runs` and a run detail
- `/experiments`
- `/settings` (every tab)
- `/chat`
- `/library`
- `/dashboard` if exists

Fix any issue you find on the spot. If a fix would touch >5 files for a single class of bug, stop and discuss with the user first.

- [ ] **Step 5: Run tests + type-check**

```bash
cd frontend && npm run check && npm run test
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
# add only the files you actually edited
git add -p
git commit -m "refactor(themes): replace hardcoded colors with tokens for dark-theme compat"
```

If multiple logical groups, split into multiple commits (e.g., `chore(themes): swap chrome colors to tokens`, `chore(themes): fix invisible-on-dark text in run editor`).

---

## Task 8: Browser verification + user signoff

- [ ] **Step 1: Restart dev servers cleanly**

Kill any running uvicorn / vite from earlier tasks. Restart:
```bash
# backend
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010
# frontend (in a separate terminal)
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183
```

- [ ] **Step 2: Launch qa-verify agent**

Dispatch the `qa-verify` agent with this brief:

> Verify the four-theme system. Login flow: register a new user OR use existing dev creds (any password works in dev — see CLAUDE.md). Visit Settings → Appearance and click each of: Lab Glass, Blueprint, Apothecary, Instrument. After each selection, walk: Dashboard, Projects → a project, Protocols → open a protocol editor, Runs → a run, Settings (all tabs). Confirm:
> - Theme applies instantly (no flash of previous theme)
> - Hard refresh preserves the theme (no flash on reload)
> - Sidebar, top bar, cards, tables, buttons, badges, dividers all use the active palette
> - No invisible text, no bright-white rectangles, no broken icons under Instrument
> - Selected theme card has visible "SELECTED" indicator
> Fix any FAIL/POLISH before returning. Frontend: http://localhost:5183/ , backend at :8010.

- [ ] **Step 3: User signoff**

Present a summary of what was built, files modified, and tests added. Wait for explicit confirmation before closeout.

- [ ] **Step 4: Closeout**

After explicit user signoff:
1. Final `git status` — clean.
2. `git log --oneline` — review commit sequence.
3. Use `ExitWorktree` with action `keep` (commits remain on `worktree-F-themes` branch for the user to merge).
4. Mention the user can merge via their normal flow (the worktree workflow does not auto-merge per CLAUDE.md).

---

## Self-review notes

- **Spec coverage:** Every requirement from the chat (4 themes, Lab Glass default, Tailwind v4, per-user persistence, anti-FOUC, settings UI with previews, audit) maps to a task above. ✔
- **Type consistency:** `Theme` type defined once in `theme.svelte.ts`; backend allowed list mirrored exactly (`lab-glass`, `blueprint`, `apothecary`, `instrument`); both list the same four. ✔
- **No placeholders:** Every code step has full code; every command has an expected outcome. ✔
- **Scope discipline:** Plan does NOT touch font-size/density (separate concern), does NOT add a `--success` token (out of scope; status badges keep their literal greens/reds/ambers — pragmatic punt), does NOT auto-detect `prefers-color-scheme`.
