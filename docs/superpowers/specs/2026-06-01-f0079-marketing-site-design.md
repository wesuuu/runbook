# F-0079 — Batchrite Marketing Site (static, Cloudflare Pages)

**Status:** Design / spec
**Date:** 2026-06-01
**Task:** [F-0079] Marketing Site & Sales Page — Public Beta Signup + Demo Booking
**Author:** wesuuu

## 1. Summary

Ship Batchrite's public marketing/sales site as a **flat static site** deployed to
**Cloudflare Pages**, hosted separately from the app.

The site is already designed and authored: three complete HTML pages and four
complete stylesheets live in `mockups/sales-wireframes/`. The remaining work is
**packaging that authored site into a deployable `marketing/` directory** with
clean URLs, production-safe assets, SEO, and Cloudflare Pages deploy config — not
designing or building pages from scratch.

This is a deliberate descope from the original F-0079 ticket (see §7). The
original locked-in stack (Astro + Tailwind 4 + MDX + `@astrojs/svelte` + server
API routes) was justified by server-side integration secrets (Loops API key).
With all integrations deferred, the site is purely static, so a framework adds
build tooling without buying any capability. Decision: **plain static HTML/CSS**.

## 2. Goals

- A `marketing/` directory that deploys to Cloudflare Pages with **no build step**
  (Framework preset: None; output dir `marketing/`).
- Clean URLs: `/`, `/about`, `/roadmap`.
- Brand-matched visual design (already present in the authored CSS).
- Pilot CTA: every "book"/"join" CTA links to
  `https://calendly.com/batchrite/founding-partner`, opening in a new tab.
- Production-safe assets: no authoring-tool runtime code shipped to the public site.
- SEO basics: per-page canonical + Open Graph + Twitter meta, favicon, `robots.txt`,
  `sitemap.xml`, an OG share image.
- Restored, working `mailto:` contact links.
- Accessible and responsive (already largely satisfied by the authored markup/CSS;
  verified, not rebuilt).

## 3. Non-Goals (deferred to follow-up tasks)

These were in the original ticket but are explicitly **out of scope** for this pass,
per scoping decisions made during brainstorming:

- **PostHog** analytics (site-wide init + funnel events).
- **Loops CRM** integration (demo-booking / newsletter contact capture + Astro API route).
- **Register `?ref=` handling** — the app's `POST /auth/register` referral attribution.
- **Public-beta subscription tier** — backend `SubscriptionTier` change.
- **Real product screenshots** — captured from the live post-rebrand app.
- **Domain registration, TLS, Cloudflare/Calendly/PostHog account setup** — dashboard
  actions, not repo code. The `marketing/README.md` documents the steps; it does not
  perform them.
- **Newsletter opt-in form** — depends on Loops; deferred with it.

Each deferred item should be filed as its own ClickUp task referencing F-0079. Two
hand-offs the follow-up tasks must carry:
- **PostHog task** must extend `marketing/_headers` CSP (`script-src` + `connect-src` for
  the PostHog host) — the snippet fails silently otherwise.
- **Register `?ref=` task** must retarget the marketing CTAs that should go to the app
  (today only nav "Sign in" → `app.batchrite.com`; the primary "Join pilot" CTAs route to
  Calendly and may be repointed to `app.batchrite.com/register?ref=marketing` then).

## 4. Source Material (current state)

In `mockups/sales-wireframes/` (untracked; user-provided):

| File | Role |
| --- | --- |
| `Batchrite.html` (1518 ln) | Landing page — 10 sections (hero, problem, features, supporting grid, data ownership, beta program, trust, coming-soon, FAQ, final CTA, footer) |
| `About.html` (781 ln) | About — values, team/advisor cards, founder modal |
| `Roadmap.html` (388 ln) | Roadmap — shipped / in-progress / next |
| `batchrite.css` (266 ln) | Base: brand tokens (`:root` custom props), typography, buttons, lockup/mark, footer |
| `batchrite-sections.css` (900 ln) | Shared section styles (used by all pages) |
| `batchrite-about.css` (1132 ln) | About-page styles |
| `batchrite-roadmap.css` (192 ln) | Roadmap-page styles |
| `image-slot.js` (641 ln) | **Authoring-tool** custom element `<image-slot>` (drag/drop + omelette sidecar persistence) |

Brand tokens (from `batchrite.css`): teal `#0A4C5C`, green `#1DA570`, amber `#F59A1A`,
ink `#122231`, bone `#F4F7F9`; fonts DM Sans / DM Mono (Google Fonts). **Canonical hex
source is `frontend/src/lib/components/layout/LogoMark.svelte`** (the `TEAL`/`GREEN`/
`BONE`/`AMBER` constants), which the marketing CSS already matches exactly — *not*
`app.css`, whose HSL `@theme` values compute to slightly different hex (e.g. primary
≈ `#084F67` vs `#0A4C5C`). On a rebrand, update `LogoMark.svelte` and
`marketing/css/batchrite.css` together; `README.md` records this lineage.

Known artifacts to fix:
- **Cross-page links** use capitalized filenames (`Batchrite.html`, `About.html`,
  `Roadmap.html`) and `Batchrite.html#anchor` forms.
- **Contact links** are Cloudflare email-obfuscation tokens
  (`/cdn-cgi/l/email-protection#<hex>`), inert without Cloudflare's `email-decode.min.js`.
  They decode via Cloudflare's XOR scheme (first byte = key) to real `@batchrite.com`
  addresses (e.g. one decodes to `pilot@batchrite.com`).
- **`<head>`** has only `title`, `description`, fonts, CSS — no canonical/OG/favicon/robots.
- **`<image-slot>`** is used only in `about.html`; all current slots are placeholders
  (initials / "drop a headshot").

## 5. Design

### 5.1 Directory layout

```
marketing/
  index.html            # from Batchrite.html
  about.html            # from About.html
  roadmap.html          # from Roadmap.html
  css/
    batchrite.css
    batchrite-sections.css
    batchrite-about.css
    batchrite-roadmap.css
  js/
    image-slot.js       # slim read-only version (see 5.3)
  favicon.svg           # brand mark
  og-image.png          # social share card (1200x630)
  robots.txt
  sitemap.xml
  _headers              # Cloudflare Pages headers (security + cache)
  README.md             # deploy + custom-domain steps
```

`mockups/sales-wireframes/` is left **untouched** as the authoring source of truth, but
is **committed to git** alongside the `marketing/` deliverable (it is currently
untracked) so the derivation history is auditable — the deployable copy should not
descend from files absent from version control. CSS/JS move into `css/`+`js/` subfolders;
the `<link>`/`<script>` paths in the HTML are updated to match.

The brand-mark SVG `<template id="brm-mark">` (~55 lines) is repeated verbatim in all
three pages and injected at runtime by an inline script. This duplication is **accepted**
for a 3-page pilot (no build step to dedupe it); editing the mark means touching all
three pages. `README.md` notes this. If the site grows past ~5 pages, revisit a minimal
include/build step.

### 5.2 URL rewriting + CTA targets

- Rename files to lowercase; Cloudflare Pages serves `about.html` at `/about`.
- Rewrite every internal link:
  - `Batchrite.html` → `/`
  - `Batchrite.html#x` → `/#x`
  - `About.html` → `/about`
  - `Roadmap.html` → `/roadmap`
  - same-page `#x` anchors unchanged.
- Cross-page anchors to verify after rewrite (named so none are missed in QA):
  `#features`, `#beta`, `#trust`, `#faq`, `#product` (3× in roadmap), `#modalities`
  (1× in about), `#values`, `#who`.
- **Calendly CTAs**: keep href (`calendly.com/batchrite/founding-partner`), add
  `target="_blank" rel="noopener"`. Appears 3× in source (index ×2, roadmap ×1).
- **About bottom "Join the SD pilot →" CTA** (`about.html`, was
  `mailto:pilot@batchrite.com`): **retarget to the Calendly URL** for consistency with
  every other pilot CTA (`target="_blank" rel="noopener"`).
- **Nav "Sign in" button** (all 3 pages, was `#beta`): **retarget to
  `https://app.batchrite.com`** (the real product login). It is the only CTA that points
  at the app; everything else routes to the pilot section or Calendly.
- **About press section** (the brand-assets block with the three `href="#"` download
  stubs — `brand-kit.zip`, `product-screens.zip`, `one-pager.pdf`): **remove the entire
  section.** No press kit ships in this pass.

### 5.3 `image-slot.js` (production, slim read-only)

Ship a **trimmed** custom element that:
- Honors the **full authoring attribute surface** so no live slot silently breaks:
  `id`, `shape`, `radius`, `mask`, `fit`, `position`, `placeholder`, `src`
  (the authoring element's `observedAttributes`). Verify against actual
  `<image-slot>` usage in `about.html` before writing it.
- Renders the styled placeholder: respects `shape` / `mask` / `radius`, shows
  `placeholder` text (initials or prompt) centered.
- Supports a `src` attribute → renders the image with `fit`/`position` when a real
  asset is supplied later.
- **Keeps the shadow-DOM internal stylesheet** the element injects for its inner
  placeholder/image. Page CSS (`batchrite-about.css`) only sizes the *host box* — the
  inner rendering comes from the component's own styles, so dropping them yields blank
  slots.
- **Drops** all omelette-runtime code: `.image-slots.state.json` sidecar, the
  `window.omelette` bridge, drag/drop, click-to-browse, reframe/crop — and critically
  the **startup `fetch()` of the sidecar**, which would 404 on Cloudflare Pages and fail
  the "zero console errors" gate. None of it can run on Pages.

Existing `<image-slot>` markup in `about.html` is unchanged. The authoring version
stays in `mockups/` for continued slot-filling.

### 5.4 Contact links

Decode each `/cdn-cgi/l/email-protection#<hex>` token (XOR, first byte = key) and
replace with the real `mailto:<address>`. There are **11 tokens across the 3 pages**;
all decode to `@batchrite.com` addresses (`pilot@`, `partners@`, `hello@`, `security@`,
`press@`). Also:
- Rewrite the **visible link text** where Cloudflare left a `[email protected]`
  placeholder span — not only the `href`.
- **Remove the 3 `email-decode.min.js` `<script>` tags** (one per page) that Cloudflare
  injected; they reference an asset that won't exist and aren't needed once links are
  real.
- Verify each decoded address is a well-formed `@batchrite.com` address before
  substituting.
- (`press@` appears only in the About press block, which is being removed per §5.2 —
  so its token disappears with that section.)

### 5.5 SEO + social

Per page `<head>` additions:
- `<link rel="canonical">` (absolute, e.g. `https://batchrite.com/about`).
- Open Graph: `og:type`, `og:title`, `og:description`, `og:url`, `og:image`, `og:site_name`.
- Twitter: `twitter:card=summary_large_image`, title/description/image.
- `<link rel="icon" href="/favicon.svg" type="image/svg+xml">`.

Root assets:
- `favicon.svg` — the brand flask mark (already an inline SVG `<template>` in each page;
  extract to a standalone file). **Hardcode the hex colors** (`#0A4C5C`, `#1DA570`,
  `#F59A1A`, `#F4F7F9`) — the inline template uses `var(--teal/green/amber/bone)`, which
  resolve to nothing in a standalone SVG and would render blank/black.
- `og-image.png` — 1200×630 branded card (wordmark + tagline on bone/teal). Generated
  asset; a simple on-brand composition is acceptable for the pilot.
- `robots.txt` — allow all, point to sitemap.
- `sitemap.xml` — the three URLs.

The canonical/OG base origin (`https://batchrite.com`) is **not** a single variable —
plain HTML has no include mechanism, so it appears ~10 times (canonical ×3, `og:url` ×3,
`sitemap.xml` ×3, `robots.txt` Sitemap pointer ×1). `README.md` documents the exact
`grep -rl 'batchrite.com' marketing/ | xargs sed -i ...` replace command to retarget the
domain in one operation.

### 5.6 Cloudflare Pages config

- `_headers` — security headers + long-cache for `/css/*`, `/js/*`, images.
  - `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
    `X-Frame-Options: DENY`.
  - **CSP must accommodate the authored markup**, which is *not* CSP-clean: the pages
    carry **203 inline `style=` attributes + an inline `<style>` block** and an **inline
    `<script>` on every page** (renders the brand mark + the About founder modal). A
    naive `style-src 'self'` / `script-src 'self'` would strip the layout and kill the
    logo site-wide. Policy:
    ```
    default-src 'self';
    style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
    font-src 'self' https://fonts.gstatic.com;
    script-src 'self' 'unsafe-inline';
    img-src 'self' data:;
    base-uri 'self';
    frame-ancestors 'none';
    ```
    `'unsafe-inline'` is an accepted trade for a static brochure with **no user input and
    no secrets** — the XSS surface is effectively nil. (Rewriting 203 inline styles +
    extracting/hashing every inline script for a pilot brochure is not worth it; revisit
    if the site grows.) **Calendly needs no CSP allowance** — the CTAs are top-level
    navigations (`<a href>`), not embedded subresources or frames.
  - **PostHog (deferred):** when analytics lands, its follow-up task **must** extend this
    CSP (`script-src` + `connect-src` for the PostHog ingest host) or the snippet fails
    silently. Noted here and in §3.
- No `_redirects` needed (clean URLs are automatic). Optionally map legacy
  `/Batchrite.html` → `/` if any external link used the old name; not required.
- Deploy: `wrangler pages deploy marketing` or Git integration (root `marketing/`,
  no build command). Documented in `README.md`.

## 6. Testing / Verification

No backend or unit-test surface (static files only). Verification is manual + tooling:

1. **Renders + CSP:** serve via **`wrangler pages dev marketing`** (mandatory — `npx
   serve` does **not** apply `_headers`, so it silently skips the CSP, the single most
   likely thing to break the page). All three pages load with full CSS, fonts, inline
   styles, and the brand mark (logo present ⇒ inline `<script>` ran under CSP);
   **zero console errors** (no `window.omelette`, no sidecar 404, no CSP violation).
2. **Links:** every internal nav/cross-page link resolves (incl. `#product`,
   `#modalities`); all Calendly CTAs — including the retargeted About bottom CTA — open
   `founding-partner` in a new tab; nav "Sign in" points to `https://app.batchrite.com`;
   every `mailto:` opens a composer with a real address and correct visible text; **zero**
   remaining `/cdn-cgi/` href or `email-decode.min.js` script; the About press section
   (the 3 download stubs) is gone.
3. **`<image-slot>`:** About page renders all placeholder slots correctly with the slim
   component; no reference to `window.omelette` or a missing sidecar in console.
4. **SEO:** view-source shows canonical + OG + Twitter + favicon on each page;
   `robots.txt` and `sitemap.xml` resolve at root; OG image loads.
5. **Responsive/a11y:** spot-check mobile and desktop breakpoints; run Lighthouse on the
   static output (target: perf ≥ 95, a11y ≥ 95).
6. **Browser QA:** `qa-verify` walks all three pages at the served URL.

## 7. Deviations from the original ticket

| Ticket said | This spec | Why |
| --- | --- | --- |
| Astro + Tailwind 4 + MDX + `@astrojs/svelte` | Plain static HTML/CSS | Integrations deferred ⇒ no server routes ⇒ framework buys nothing; site already authored as static HTML/CSS |
| Deploy to Vercel/Netlify | Cloudflare Pages | User requirement; pages already saved-from-Cloudflare |
| PostHog / Loops / register `?ref=` / public-beta tier | Deferred (§3) | Scoped to "marketing site shell only" |
| Sections "with screenshots" | Placeholder image slots | Real screenshots deferred (post-rebrand capture) |
| Pricing replaced by Beta-program block | Already present in authored markup | n/a |

## 8. Risks

- **Low overall** — static files, no app coupling, no DB, no backend.
- **CSP strips the page (highest-likelihood failure):** the markup leans on 203 inline
  `style=` attrs + inline `<style>` and an inline `<script>` per page. A `style-src`/
  `script-src` without `'unsafe-inline'` removes layout and kills the logo. Mitigation:
  the §5.6 CSP allows inline style+script; **test under `wrangler pages dev`** (not
  `npx serve`, which ignores `_headers`).
- **`<image-slot>` slim rewrite:** must honor the full attribute set *and* keep the
  component's shadow-DOM styles, or slots render blank; the sidecar `fetch` must be
  removed or it 404s and fails the zero-console-errors gate. Mitigation: enumerate live
  attributes from `about.html`, test that page specifically.
- **Email decode correctness:** a wrong XOR decode yields a bad address, and the visible
  `[email protected]` text must be fixed too. Mitigation: decode is deterministic;
  sanity-check each result is a well-formed `@batchrite.com` address; grep that zero
  `cdn-cgi` hrefs/scripts remain.
- **OG base origin:** if the live domain isn't `batchrite.com`, canonical/OG/sitemap URLs
  are wrong until updated. Mitigation: ~10 occurrences, retargeted by the one documented
  `grep | sed` command in `README.md`.
- **Brand drift:** marketing hex is hand-copied from `LogoMark.svelte`; a rebrand that
  edits only the app drifts the site. Mitigation: `README.md` records the lineage and the
  two files to update together.
