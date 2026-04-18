# Logo Implementation Specification

## Overview

Replace all hardcoded "B" and "R" badge logos throughout the frontend with the new Batchrite logo image (currently at `frontend/src/assets/logo.png`), plus set the site favicon.

## Current State

**Logo locations:**
- Header navigation (`+layout.svelte:143-147`) — Blue badge with white "B" text
- Loading state (`+layout.svelte:111-114`) — Badge with "R" text + pulsing border animation
- Login page (`login/+page.svelte:40-44`) — Blue badge with white "B" text
- Mobile nav (`MobileNav.svelte:44-47`) — Badge with "R" text and "Runbook" label (inconsistent)
- Favicon — Not currently set to custom logo

**Logo asset:** `frontend/src/assets/logo.png` (357x320px PNG)

## Design

### 1. Reusable Logo Component

Create `lib/components/Logo.svelte` — a simple image component:

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

### 2. Updated Locations

#### Header Navigation (+layout.svelte:143-147)
Replace the badge div + span with:
```svelte
<Logo size="md" />
```
Keep the surrounding link structure and hover effects intact.

#### Loading State (+layout.svelte:111-114)
Replace the badge div + animated border div with:
```svelte
<div class="relative">
    <Logo size="md" />
</div>
```
No pulsing animation on the logo itself.

#### Login Page (login/+page.svelte:40-44)
Replace the badge div + span with:
```svelte
<Logo size="lg" />
```

#### Mobile Nav (MobileNav.svelte:44-47)
- Replace the badge div + span with `<Logo size="md" />`
- Change text from "Runbook" to "Batchrite" (line 47)

### 3. Favicon

Add favicon to `src/app.html` `<head>`:
```html
<link rel="icon" type="image/png" href="/logo.png" />
```

Use `logo.png` directly as favicon (modern browsers support PNG format). If ICO format is needed, can convert the 357x320px PNG to a 32x32px .ico file using an image tool.

## Implementation Plan

1. Create `Logo.svelte` component
2. Update +layout.svelte (header + loading state)
3. Update login/+page.svelte
4. Update MobileNav.svelte (fix "Runbook" → "Batchrite")
5. Add favicon link to app.html
6. Test all locations with different viewport sizes

## Testing

- Verify logo displays correctly at all sizes
- Check hover effects still work on header/login links
- Confirm favicon appears in browser tabs
- Test on mobile viewport (MobileNav)
- Test loading state with slow network

## Notes

- All existing hover effects and shadows on parent elements remain unchanged
- Logo sizing is conservative to maintain clear display at small sizes
- Component accepts optional `class` prop for flexibility if needed later
