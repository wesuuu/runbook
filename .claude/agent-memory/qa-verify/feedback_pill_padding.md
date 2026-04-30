---
name: Filter pill vertical padding
description: DM Sans font metrics require py-1.5 minimum for rounded-full pills to avoid text appearing clipped
type: feedback
---

Filter pills using `rounded-full` + `text-xs` + DM Sans need at least `py-1.5` (6px) vertical padding to prevent descenders appearing to touch the pill border arc.

**Why:** DM Sans has a high UPM with large ascenders/descenders (900/-200 out of 1000). At 12px, glyphs span ~13.2px total height. With only `py-1` (4px), clearance from glyph extreme to border is ~3.4px — visually cramped, especially for 'p', 'g', 'y' descenders in the selected (highlighted) state. `leading-5` was tried first but only addressed line-height, not the padding gap. The actual fix was `py-1.5`.

**Confirmed working (2026-04-17):** Screenshot-verified with Playwright at 6x deviceScaleFactor. With `py-1.5` applied:
- `paddingTop: 6px`, `paddingBottom: 6px` confirmed via `window.getComputedStyle`
- Text range metrics: `spaceAbove: 7px`, `spaceBelow: 7px` — 7px breathing room on all sides
- Pill height: `30px` (6 + 1 border + 16 line-height + 6 + 1 border = 30px)
- All glyph descenders ('p', 'g', 'y', 'd') have clear visible space below in both light and dark active states
- No clipping visible at 6x zoom on any pill variant (Protocol sky-blue, Created/Updated/etc slate-800)

**How to apply:** Any `rounded-full` pill component using `text-xs` with DM Sans should use `py-1.5` minimum. Do not use `leading-5` as a workaround for insufficient padding — they solve different problems. `leading-5` is for controlling line spacing in multi-line text; `py-1.5` is for controlling the gap between glyphs and the border.

**Screenshot method:** Use Playwright with `deviceScaleFactor: 4` or higher and clip tightly to the pill element. Run script as `.cjs` from `frontend/` directory where playwright is installed. Login user: `upstream.lead@bioprocess.com` / `password123`. Project ID for mAb Production v2: `40000000-0000-0000-0000-000000000001`.
