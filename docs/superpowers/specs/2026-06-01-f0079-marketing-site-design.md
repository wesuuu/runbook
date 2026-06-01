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

Each deferred item should be filed as its own ClickUp task referencing F-0079.

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

Brand tokens (from `batchrite.css`, drawn from the app's `app.css`): teal `#0A4C5C`,
green `#1DA570`, amber `#F59A1A`, ink `#122231`, bone `#F4F7F9`; fonts DM Sans / DM Mono
(Google Fonts).

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

`mockups/sales-wireframes/` is left **untouched** as the authoring source of truth.
`marketing/` is the deployable copy. CSS/JS move into `css/`+`js/` subfolders; the
`<link>`/`<script>` paths in the HTML are updated to match.

### 5.2 URL rewriting

- Rename files to lowercase; Cloudflare Pages serves `about.html` at `/about`.
- Rewrite every internal link:
  - `Batchrite.html` → `/`
  - `Batchrite.html#x` → `/#x`
  - `About.html` → `/about`
  - `Roadmap.html` → `/roadmap`
  - same-page `#x` anchors unchanged.
- Calendly CTAs: keep href, add `target="_blank" rel="noopener"`.

### 5.3 `image-slot.js` (production, slim read-only)

Ship a **trimmed** custom element that:
- Renders the styled placeholder: respects `shape` / `mask` / `radius`, shows
  `placeholder` text (initials or prompt) centered.
- Supports a `src` attribute → renders the image with `fit`/`position` when a real
  asset is supplied later.
- **Drops** all omelette-runtime code: `.image-slots.state.json` sidecar,
  `window.omelette` bridge, drag/drop, click-to-browse, reframe/crop. None of it can
  run on Cloudflare Pages.

Existing `<image-slot>` markup in `about.html` is unchanged; the attributes it uses
(`id`, `shape`, `placeholder`, `class`) are all honored. The authoring version stays
in `mockups/` for continued slot-filling.

The CSS already styles `image-slot` directly (`batchrite-about.css`), so the slim
element only needs to render its inner placeholder/image; box styling comes from CSS.

### 5.4 Contact links

Decode each `/cdn-cgi/l/email-protection#<hex>` token (XOR, first byte = key) and
replace with the real `mailto:<address>`. Verify each decoded address is a plausible
`@batchrite.com` address before substituting.

### 5.5 SEO + social

Per page `<head>` additions:
- `<link rel="canonical">` (absolute, e.g. `https://batchrite.com/about`).
- Open Graph: `og:type`, `og:title`, `og:description`, `og:url`, `og:image`, `og:site_name`.
- Twitter: `twitter:card=summary_large_image`, title/description/image.
- `<link rel="icon" href="/favicon.svg" type="image/svg+xml">`.

Root assets:
- `favicon.svg` — the brand flask mark (already an inline SVG `<template>` in each page;
  extract to a standalone file).
- `og-image.png` — 1200×630 branded card (wordmark + tagline on bone/teal). Generated
  asset; a simple on-brand composition is acceptable for the pilot.
- `robots.txt` — allow all, point to sitemap.
- `sitemap.xml` — the three URLs.

The canonical/OG base origin is configurable in one place in `README.md`; default
`https://batchrite.com`. If the production domain differs, it is a find/replace of the
base origin.

### 5.6 Cloudflare Pages config

- `_headers` — security headers (`X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`, a conservative CSP allowing
  Google Fonts + Calendly, `X-Frame-Options`) and long-cache for `/css/*`, `/js/*`,
  images.
- No `_redirects` needed (clean URLs are automatic). Optionally map legacy
  `/Batchrite.html` → `/` if any external link used the old name; not required.
- Deploy: `wrangler pages deploy marketing` or Git integration (root `marketing/`,
  no build command). Documented in `README.md`.

## 6. Testing / Verification

No backend or unit-test surface (static files only). Verification is manual + tooling:

1. **Renders:** serve `marketing/` locally (`npx serve marketing` or
   `wrangler pages dev marketing`); all three pages load with full CSS, fonts, and the
   brand mark; **zero console errors**.
2. **Links:** every internal nav/cross-page link resolves; all Calendly CTAs open
   `founding-partner` in a new tab; every `mailto:` opens a composer with a real address;
   no remaining `/cdn-cgi/` href.
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
- **CSP / Calendly + Google Fonts:** an over-tight CSP in `_headers` could block fonts or
  the Calendly popup. Mitigation: explicitly allow `fonts.googleapis.com`,
  `fonts.gstatic.com`, and `calendly.com`; verify in the render check.
- **`<image-slot>` slim rewrite:** must honor the exact attributes used in `about.html`
  or slots render blank. Mitigation: enumerate used attributes from `about.html` and test
  that page specifically.
- **Email decode correctness:** a wrong XOR decode yields a bad address. Mitigation: decode
  is deterministic; sanity-check each result is a well-formed `@batchrite.com` address.
- **OG base origin:** if the live domain isn't `batchrite.com`, canonical/OG URLs are wrong
  until the base is updated. Mitigation: single documented find/replace point.
