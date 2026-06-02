# F-0079 Marketing Site (static, Cloudflare Pages) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the already-authored Batchrite marketing wireframes into a deployable, production-safe static site under `marketing/`, ready for Cloudflare Pages.

**Architecture:** Copy the three authored HTML pages + four stylesheets from `mockups/sales-wireframes/` into a flat `marketing/` directory (no build step). Rewrite internal links to clean URLs, retarget CTAs, restore real `mailto:` links, ship a slimmed read-only `<image-slot>`, add SEO/social/deploy assets, and a CSP that tolerates the authored inline styles/scripts.

**Tech Stack:** Plain HTML5 + CSS (bespoke, DM Sans/Mono via Google Fonts), one vanilla-JS Web Component, Cloudflare Pages (`_headers`, `wrangler pages dev` for local verification). No framework, no bundler, no backend.

**Spec:** `docs/superpowers/specs/2026-06-01-f0079-marketing-site-design.md`

> **Testing note:** static-site work has no unit-test surface. Each task's "test" is a deterministic **grep/render assertion** (an exact command + expected output) instead of a `pytest`. The final task runs the full browser + Lighthouse pass.

---

## File Structure

```
marketing/
  index.html            # from Batchrite.html (landing)
  about.html            # from About.html
  roadmap.html          # from Roadmap.html
  css/
    batchrite.css            # base: tokens, type, buttons, lockup, footer
    batchrite-sections.css   # shared section styles
    batchrite-about.css      # about page
    batchrite-roadmap.css    # roadmap page
  js/
    image-slot.js       # slim read-only custom element (NEW, not a copy)
  assets/
    og-image.svg        # social card source
    og-image.png        # rasterized 1200x630 (referenced by OG meta)
  favicon.svg           # brand mark, hardcoded hex
  robots.txt
  sitemap.xml
  _headers              # CSP + security + cache
  README.md             # deploy, domain retarget, brand lineage, brm-mark note
```

`mockups/sales-wireframes/` stays as the authoring source and is **committed** (Task 0).

---

### Task 0: Commit the authoring source

**Files:**
- Track: `mockups/sales-wireframes/` (currently untracked)

- [ ] **Step 1: Stage and commit the source-of-truth wireframes**

The `marketing/` deliverable derives from these files; they must be in git history for auditability (spec §5.1).

```bash
cd /home/wesuuu/Code/trellisbio
git add mockups/sales-wireframes/
git commit -m "chore(F-0079): commit marketing wireframe source (HTML/CSS/image-slot authoring)"
```

- [ ] **Step 2: Verify**

Run: `git ls-files mockups/sales-wireframes/ | sort`
Expected: lists `About.html Batchrite.html Roadmap.html batchrite-about.css batchrite-roadmap.css batchrite-sections.css batchrite.css image-slot.js`

---

### Task 1: Scaffold `marketing/` + relocate assets

**Files:**
- Create: `marketing/index.html`, `marketing/about.html`, `marketing/roadmap.html`
- Create: `marketing/css/{batchrite,batchrite-sections,batchrite-about,batchrite-roadmap}.css`

- [ ] **Step 1: Create the directory tree and copy files**

```bash
cd /home/wesuuu/Code/trellisbio
mkdir -p marketing/css marketing/js marketing/assets
cp mockups/sales-wireframes/Batchrite.html marketing/index.html
cp mockups/sales-wireframes/About.html     marketing/about.html
cp mockups/sales-wireframes/Roadmap.html   marketing/roadmap.html
cp mockups/sales-wireframes/batchrite.css           marketing/css/
cp mockups/sales-wireframes/batchrite-sections.css  marketing/css/
cp mockups/sales-wireframes/batchrite-about.css     marketing/css/
cp mockups/sales-wireframes/batchrite-roadmap.css   marketing/css/
```

- [ ] **Step 2: Repoint the `<link rel="stylesheet">` hrefs to `css/`**

The pages reference `batchrite.css` etc. at the root; they now live in `css/`. Use a
**root-absolute** path (`/css/…`) for a uniform convention with `/favicon.svg` and so the
links don't break if a nested route is ever added.

```bash
cd /home/wesuuu/Code/trellisbio/marketing
sed -i 's|href="batchrite|href="/css/batchrite|g' index.html about.html roadmap.html
```

- [ ] **Step 3: Verify CSS links updated, no root-level refs remain**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && grep -h 'rel="stylesheet"' *.html | grep -oE 'href="[^"]*"' | sort -u`
Expected: every href starts with `/css/batchrite` (e.g. `href="/css/batchrite.css"`). No bare `href="batchrite...`.

- [ ] **Step 4: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/
git commit -m "feat(F-0079): scaffold marketing/ with pages + stylesheets in css/"
```

---

### Task 2: Slim read-only `<image-slot>` component

**Files:**
- Create: `marketing/js/image-slot.js`
- Modify: `marketing/about.html` (script src path)

The authoring component (`mockups/sales-wireframes/image-slot.js`, 641 ln) depends on `window.omelette`, a sidecar `fetch`, drag/drop, and reframe/crop — none of which run on Cloudflare Pages, and the startup sidecar fetch would 404 (failing the zero-console-errors gate). Ship a fresh read-only element that renders the placeholder + an optional `src`, keeping its shadow-DOM styles (page CSS only sizes the host box).

- [ ] **Step 1: Write `marketing/js/image-slot.js`**

```javascript
/**
 * <image-slot> — read-only image placeholder (production / Cloudflare Pages).
 *
 * Slimmed from the authoring component in
 * mockups/sales-wireframes/image-slot.js. Renders a styled placeholder
 * (shape / mask / radius + caption) and, when a `src` is supplied, the image
 * (object-fit per `fit` / `position`). All authoring-runtime code — the
 * window.omelette sidecar, its startup fetch, drag/drop, click-to-browse, and
 * reframe/crop — is removed; none of it can run on a static CDN.
 *
 * Honored attributes:
 *   shape     'rect' | 'rounded' | 'circle' | 'pill'   (default 'rounded')
 *   radius, mask, fit, position, placeholder, src
 * (`id` stays a plain HTML attribute for CSS targeting; it is no longer a
 * persistence key. `shape="rect"` matches no radius branch -> square corners.)
 */
(function () {
  'use strict';

  const icon =
    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>' +
    '<path d="m21 15-5-5L5 21"/></svg>';

  const stylesheet =
    ':host{display:inline-block;position:relative;vertical-align:top;' +
    '  font:13px/1.3 system-ui,-apple-system,sans-serif;color:rgba(0,0,0,.55);' +
    '  width:240px;height:160px}' +
    '.frame{position:absolute;inset:0;overflow:hidden;background:rgba(0,0,0,.04)}' +
    '.frame img{position:absolute;inset:0;width:100%;height:100%}' +
    '.empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;' +
    '  justify-content:center;gap:6px;text-align:center;padding:12px;box-sizing:border-box;' +
    '  user-select:none}' +
    '.empty svg{opacity:.45}' +
    '.empty .cap{max-width:90%;font-weight:500;letter-spacing:.01em}' +
    '.ring{position:absolute;inset:0;pointer-events:none;border:1.5px dashed rgba(0,0,0,.25)}' +
    ':host([data-filled]) .ring{display:none}';

  class ImageSlot extends HTMLElement {
    static get observedAttributes() {
      return ['shape', 'radius', 'mask', 'fit', 'position', 'placeholder', 'src'];
    }

    constructor() {
      super();
      const root = this.attachShadow({ mode: 'open' });
      root.innerHTML =
        '<style>' + stylesheet + '</style>' +
        '<div class="frame" part="frame">' +
        '  <img part="image" alt="" draggable="false" style="display:none">' +
        '  <div class="empty" part="empty">' + icon + '<div class="cap"></div></div>' +
        '  <div class="ring" part="ring"></div>' +
        '</div>';
      this._frame = root.querySelector('.frame');
      this._ring = root.querySelector('.ring');
      this._img = root.querySelector('.frame img');
      this._empty = root.querySelector('.empty');
      this._cap = root.querySelector('.cap');
    }

    connectedCallback() { this._render(); }
    attributeChangedCallback() { if (this.shadowRoot) this._render(); }

    _render() {
      const mask = this.getAttribute('mask');
      const shape = (this.getAttribute('shape') || 'rounded').toLowerCase();
      let radius = '';
      if (shape === 'circle') radius = '50%';
      else if (shape === 'pill') radius = '9999px';
      else if (shape === 'rounded') {
        const n = parseFloat(this.getAttribute('radius'));
        radius = (Number.isFinite(n) ? n : 12) + 'px';
      }
      this._frame.style.borderRadius = mask ? '' : radius;
      this._frame.style.clipPath = mask || '';
      this._ring.style.borderRadius = mask ? '' : radius;
      this._ring.style.display = mask ? 'none' : '';

      this._cap.textContent = this.getAttribute('placeholder') || 'Image';

      const url = this.getAttribute('src') || '';
      if (url) {
        this._img.src = url;
        this._img.style.objectFit = this.getAttribute('fit') || 'cover';
        this._img.style.objectPosition = this.getAttribute('position') || '50% 50%';
        this._img.style.display = 'block';
        this._empty.style.display = 'none';
        this.setAttribute('data-filled', '');
      } else {
        this._img.removeAttribute('src');
        this._img.style.display = 'none';
        this._empty.style.display = 'flex';
        this.removeAttribute('data-filled');
      }
    }
  }

  if (!customElements.get('image-slot')) {
    customElements.define('image-slot', ImageSlot);
  }
})();
```

- [ ] **Step 2: Repoint About's script tag to `js/image-slot.js`**

About references `image-slot.js` at the root.

```bash
cd /home/wesuuu/Code/trellisbio/marketing
sed -i 's|src="image-slot.js"|src="/js/image-slot.js"|' about.html
```

- [ ] **Step 3: Verify the slim file is omelette-free and the path is fixed**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && grep -c 'omelette\|writeFile\|ResizeObserver\|fetch(' js/image-slot.js; grep -o 'src="/js/image-slot.js"' about.html`
Expected: first count is `0`; second prints `src="/js/image-slot.js"`.

- [ ] **Step 4: Confirm About uses only honored attributes**

Run: `grep -oE '<image-slot[^>]*>' mockups/sales-wireframes/About.html | grep -oE '[a-z-]+=' | sort -u`
Expected: only `class=`, `id=`, `shape=`, `placeholder=` appear — all supported (`id`/`class` are plain HTML; `shape`/`placeholder` are observed). If any of `radius/mask/fit/position/src` show up, they are also supported — no action; just confirm nothing unexpected.

- [ ] **Step 5: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/js/image-slot.js marketing/about.html
git commit -m "feat(F-0079): slim read-only <image-slot> for production"
```

---

### Task 3: Rewrite internal links + retarget CTAs + remove press section

**Files:**
- Modify: `marketing/index.html`, `marketing/about.html`, `marketing/roadmap.html`

- [ ] **Step 1: Rewrite cross-page links to clean URLs**

Order matters: rewrite the `#anchor` forms before the bare filename so `Batchrite.html#x` becomes `/#x`, not `/...html#x`.

```bash
cd /home/wesuuu/Code/trellisbio/marketing
for f in index.html about.html roadmap.html; do
  sed -i \
    -e 's|href="Batchrite.html#|href="/#|g' \
    -e 's|href="Batchrite.html"|href="/"|g' \
    -e 's|href="About.html"|href="/about"|g' \
    -e 's|href="Roadmap.html"|href="/roadmap"|g' \
    "$f"
done
```

- [ ] **Step 2: Verify no capitalized `.html` cross-links remain**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && grep -oE 'href="[^"]*\.html[^"]*"' *.html | grep -iE 'Batchrite|About\.html|Roadmap\.html' || echo "CLEAN"`
Expected: `CLEAN`.

- [ ] **Step 3: Retarget the nav "Sign in" buttons to the app**

"Sign in" should open the product login. It comes in **two href forms**: `index.html`
(the landing page) has the bare same-page anchor `href="#beta"` (Step 1 doesn't touch it,
since Step 1 only rewrites `Batchrite.html#…`), while `about.html`/`roadmap.html` produce
`href="/#beta"` after Step 1. Cover both, matching on the `Sign in` text to leave the
adjacent "Join SD pilot" CTA (which keeps `/#beta`) untouched.

```bash
cd /home/wesuuu/Code/trellisbio/marketing
sed -i \
  -e 's|href="/#beta" class="btn btn-ghost">Sign in|href="https://app.batchrite.com" class="btn btn-ghost">Sign in|g' \
  -e 's|href="#beta" class="btn btn-ghost">Sign in|href="https://app.batchrite.com" class="btn btn-ghost">Sign in|g' \
  index.html about.html roadmap.html
```

- [ ] **Step 4: Add `target="_blank" rel="noopener"` to the Calendly CTAs**

Some Calendly links already carry `target="_blank" rel="noopener"` (e.g. index "Book a 30-min call"); add it only where missing. Match the bare-href form.

```bash
cd /home/wesuuu/Code/trellisbio/marketing
sed -i 's|href="https://calendly.com/batchrite/founding-partner"\([^>]*\)class=|href="https://calendly.com/batchrite/founding-partner" target="_blank" rel="noopener"\1class=|g; s| target="_blank" rel="noopener" target="_blank" rel="noopener"| target="_blank" rel="noopener"|g' index.html about.html roadmap.html
```

- [ ] **Step 5: Retarget About's bottom "Join the SD pilot" CTA to Calendly**

It currently encodes `mailto:pilot@…` as a Cloudflare token (`class="btn btn-on-dark">Join
the SD pilot`). Replace that whole `<a …>` href with Calendly. Use Python — a `sed`
`#`-delimiter collides with the `#` inside the `email-protection#…` token, so the sed form
is unreliable; Python is the primary path:

```bash
cd /home/wesuuu/Code/trellisbio/marketing
python3 - <<'PY'
import re, pathlib
p = pathlib.Path("about.html"); s = p.read_text()
s, n = re.subn(
    r'<a href="/cdn-cgi/l/email-protection#[^"]*"(\s+class="btn btn-on-dark">Join the SD pilot)',
    '<a href="https://calendly.com/batchrite/founding-partner" target="_blank" rel="noopener"\\1',
    s)
assert n == 1, f"expected 1 replacement, made {n}"
p.write_text(s)
print("about bottom CTA -> calendly")
PY
```

- [ ] **Step 6: Remove the entire "Press & contact" section**

Confirmed DOM (verified in source): the dead download stubs live in
`<section class="press" id="press">…</section>`, which holds **two** cards — a contact
card (`pilot@` + `security@` rows) and a journalist card (`press@` + the 3 `href="#"`
download stubs). Per the product decision, **remove the whole section** (the `security@`
contact goes with it — it appears nowhere else; this is intentional). The slice below
targets the `<section class="press">` that contains `brand-kit.zip`; that section *is*
the whole press block, so `rindex("<section", …)` lands on its opening tag.

```bash
cd /home/wesuuu/Code/trellisbio/marketing
python3 - <<'PY'
import pathlib
p = pathlib.Path("about.html"); s = p.read_text()
idx = s.index("brand-kit.zip")
start = s.rindex("<section", 0, idx)
end = s.index("</section>", idx) + len("</section>")
removed = s[start:end]
# guard: the slice must be the press section and nothing more/less
assert 'class="press"' in removed, "slice did not start at the press section"
assert all(x in removed for x in ("brand-kit.zip", "product-screens.zip", "one-pager.pdf")), "missing download stubs"
assert "Press &amp; contact" in removed, "slice missing press heading"
# guard: must NOT swallow a neighbour (final-CTA / values / team sections)
assert "final-cta" not in removed and "Build the" not in removed, "slice swallowed the final CTA"
s = s[:start] + s[end:]
p.write_text(s)
print("removed press section:", len(removed), "chars")
PY
```

- [ ] **Step 6b: Remove any now-dangling `#press` anchor links**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && grep -rn 'href="[^"]*#press"' *.html || echo "no #press links"`
If any exist (nav/footer), drop that link item. Expected after fix: `no #press links`.

- [ ] **Step 7: Verify CTAs + press removal**

Run:
```bash
cd /home/wesuuu/Code/trellisbio/marketing
echo "sign-in -> app:"; grep -c 'href="https://app.batchrite.com" class="btn btn-ghost">Sign in' index.html about.html roadmap.html
echo "calendly links w/ target:"; grep -oE 'calendly.com/batchrite/founding-partner" target="_blank"' *.html | wc -l
echo "press gone (expect 0):"; grep -c 'brand-kit.zip\|product-screens.zip\|one-pager.pdf' about.html
echo "about bottom cta -> calendly (expect 1):"; grep -c 'calendly.com/batchrite/founding-partner" target="_blank" rel="noopener" class="btn btn-on-dark">Join the SD pilot' about.html
```
Expected: each page reports `1` Sign-in; Calendly-with-target count ≥ 4 (index ×2, roadmap ×1, about bottom ×1); press count `0`; about bottom CTA `1`.

- [ ] **Step 8: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/
git commit -m "feat(F-0079): clean URLs, retarget CTAs (sign-in->app, about->calendly), drop press section"
```

---

### Task 4: Restore real `mailto:` links (decode Cloudflare tokens)

**Files:**
- Modify: `marketing/index.html`, `marketing/about.html`, `marketing/roadmap.html`

Two encoded forms remain: `href="/cdn-cgi/l/email-protection#<hex>"` and visible
`<span class="__cf_email__" data-cfemail="<hex>">[email&#160;protected]</span>`. Each
page also has an injected `<script … email-decode.min.js></script>` that sits **on the
same line, immediately before the page's own inline brand-mark `<script>`** — remove only
the decode tag.

- [ ] **Step 1: Decode + replace, in one deterministic pass**

```bash
cd /home/wesuuu/Code/trellisbio/marketing
python3 - <<'PY'
import re, pathlib

def decode(hexstr):
    b = bytes.fromhex(hexstr)
    key = b[0]
    return ''.join(chr(c ^ key) for c in b[1:])

EMAIL_DECODE_TAG = ('<script data-cfasync="false" '
    'src="/cdn-cgi/scripts/5c5dd728/cloudflare-static/email-decode.min.js"></script>')

for name in ("index.html", "about.html", "roadmap.html"):
    p = pathlib.Path(name); s = p.read_text()

    # 1) visible spans: <span class="__cf_email__" data-cfemail="HEX">…</span> -> address text
    s = re.sub(r'<span class="__cf_email__" data-cfemail="([0-9a-fA-F]+)">.*?</span>',
               lambda m: decode(m.group(1)), s)

    # 2) href tokens: href="/cdn-cgi/l/email-protection#HEX" -> mailto:address
    s = re.sub(r'href="/cdn-cgi/l/email-protection#([0-9a-fA-F]+)"',
               lambda m: 'href="mailto:%s"' % decode(m.group(1)), s)

    # 3) remove ONLY the email-decode script tag (leaves the trailing brand-mark <script>)
    s = s.replace(EMAIL_DECODE_TAG, "")

    p.write_text(s)
    print(name, "done")
PY
```

- [ ] **Step 2: Verify zero Cloudflare residue and well-formed addresses**

Run:
```bash
cd /home/wesuuu/Code/trellisbio/marketing
echo "cdn-cgi refs (expect 0):"; grep -c 'cdn-cgi' *.html
echo "__cf_email__ (expect 0):"; grep -c '__cf_email__' *.html
echo "mailto addresses:"; grep -oE 'mailto:[a-zA-Z0-9._%+-]+@batchrite\.com' *.html | sort | uniq -c
```
Expected: all `cdn-cgi` counts `0`; all `__cf_email__` counts `0`; mailto list shows only
`@batchrite.com` addresses — `pilot@` (the conference note on index), `partners@`, and
`hello@`. **`security@` and `press@` are NOT present** — they lived only in the About
press section removed in Task 3, and the About bottom `pilot@` CTA became Calendly. (If
`security@`/`press@` appear, Task 3's section removal didn't run before this task.)

- [ ] **Step 3: Verify the brand-mark inline script survived**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && grep -c "getElementById('brm-mark')" index.html about.html roadmap.html`
Expected: `1` per page (the logo injector is intact).

- [ ] **Step 4: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/
git commit -m "fix(F-0079): decode Cloudflare email tokens to real mailto: links"
```

---

### Task 5: `favicon.svg` (hardcoded hex) + favicon links

**Files:**
- Create: `marketing/favicon.svg`
- Modify: `marketing/index.html`, `marketing/about.html`, `marketing/roadmap.html`

The inline `<template id="brm-mark">` SVG uses `var(--teal/green/amber/bone)`, which resolve to nothing in a standalone file. Author a self-contained favicon with literal hex.

- [ ] **Step 1: Create `marketing/favicon.svg`** (simple flask mark, brand hex)

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <rect width="100" height="100" rx="20" fill="#F4F7F9"/>
  <g clip-path="url(#c)">
    <path d="M 41 14 L 59 14 L 59 38 A 24 24 0 1 1 41 38 Z" fill="#F4F7F9"/>
    <circle cx="50" cy="60" r="18" fill="#1DA570" opacity=".10"/>
    <g stroke="#1DA570" stroke-width="1.5" fill="none" stroke-linejoin="round" stroke-linecap="round">
      <path d="M 50 60 L 50 54 L 42 54 L 42 46 L 38 46"/>
      <path d="M 50 60 L 56 60 L 56 50 L 62 50 L 62 46"/>
      <path d="M 50 60 L 44 60 L 44 68 L 38 68 L 38 74"/>
      <path d="M 50 60 L 64 60 L 64 56 L 70 56"/>
    </g>
    <g stroke="#F59A1A" stroke-width="1.5" fill="none" stroke-linejoin="round" stroke-linecap="round">
      <path d="M 50 60 L 50 50 L 46 50 L 46 42"/>
      <path d="M 50 60 L 58 60 L 58 68 L 64 68 L 64 74"/>
    </g>
    <circle cx="50" cy="60" r="3" fill="#F4F7F9" stroke="#0A4C5C" stroke-width="1.2"/>
    <circle cx="50" cy="60" r="1.3" fill="#F59A1A"/>
  </g>
  <path d="M 41 14 L 59 14 L 59 38 A 24 24 0 1 1 41 38 Z" fill="none" stroke="#0A4C5C" stroke-width="3"/>
  <defs><clipPath id="c"><path d="M 41 14 L 59 14 L 59 38 A 24 24 0 1 1 41 38 Z"/></clipPath></defs>
</svg>
```

- [ ] **Step 2: Add the favicon `<link>` to each page `<head>`** (after the `<title>` line)

```bash
cd /home/wesuuu/Code/trellisbio/marketing
for f in index.html about.html roadmap.html; do
  sed -i 's|</title>|</title>\n<link rel="icon" href="/favicon.svg" type="image/svg+xml" />|' "$f"
done
```

- [ ] **Step 3: Verify**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && grep -c 'rel="icon"' *.html && head -c 60 favicon.svg`
Expected: `1` per page; favicon starts with the `<svg` declaration.

- [ ] **Step 4: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/favicon.svg marketing/*.html
git commit -m "feat(F-0079): standalone favicon.svg + per-page favicon link"
```

---

### Task 6: Per-page SEO + social meta

**Files:**
- Modify: `marketing/index.html`, `marketing/about.html`, `marketing/roadmap.html`

Each `<head>` has only `title`/`description`. Add canonical + Open Graph + Twitter. Base
origin `https://batchrite.com` (retargetable per README; spec §5.5).

- [ ] **Step 1: Insert the meta block per page**

Run this Python (keeps per-page title/description/url/path correct):

```bash
cd /home/wesuuu/Code/trellisbio/marketing
python3 - <<'PY'
import pathlib, re
ORIGIN = "https://batchrite.com"
PAGES = {
  "index.html":   ("/",        "Batchrite — Digital batch records + AI process memory for process development"),
  "about.html":   ("/about",   "About — Batchrite"),
  "roadmap.html": ("/roadmap", "Roadmap — Batchrite"),
}
for name,(path,title) in PAGES.items():
    p = pathlib.Path(name); s = p.read_text()
    desc = re.search(r'<meta name="description" content="([^"]*)"', s)
    desc = desc.group(1) if desc else "Batchrite"
    url = ORIGIN + path
    block = f'''<link rel="canonical" href="{url}" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Batchrite" />
<meta property="og:title" content="{title}" />
<meta property="og:description" content="{desc}" />
<meta property="og:url" content="{url}" />
<meta property="og:image" content="{ORIGIN}/assets/og-image.png" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{title}" />
<meta name="twitter:description" content="{desc}" />
<meta name="twitter:image" content="{ORIGIN}/assets/og-image.png" />'''
    # insert right after the description meta tag
    s = re.sub(r'(<meta name="description" content="[^"]*"\s*/?>)',
               r'\1\n' + block, s, count=1)
    p.write_text(s)
    print(name, "meta added")
PY
```

- [ ] **Step 2: Verify**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && for f in *.html; do echo "== $f"; grep -cE 'rel="canonical"|og:title|twitter:card' $f; done`
Expected: each file reports `3` (one canonical, one og:title, one twitter:card).

- [ ] **Step 3: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/*.html
git commit -m "feat(F-0079): canonical + Open Graph + Twitter meta per page"
```

---

### Task 7: OG share image

**Files:**
- Create: `marketing/assets/og-image.svg`, `marketing/assets/og-image.png`

- [ ] **Step 1: Author `marketing/assets/og-image.svg`** (1200×630 brand card)

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#0A4C5C"/>
  <rect x="0" y="0" width="1200" height="8" fill="#1DA570"/>
  <text x="80" y="300" font-family="DM Sans, system-ui, sans-serif" font-size="84"
        font-weight="700" fill="#F4F7F9" letter-spacing="-2">batchrite</text>
  <text x="84" y="372" font-family="DM Sans, system-ui, sans-serif" font-size="34"
        fill="#9fc7cf">Digital batch records + AI process memory</text>
  <text x="84" y="420" font-family="DM Sans, system-ui, sans-serif" font-size="34"
        fill="#9fc7cf">built for process development.</text>
  <text x="80" y="560" font-family="DM Mono, monospace" font-size="22"
        fill="#F59A1A">San Diego pilot cohort — open</text>
</svg>
```

- [ ] **Step 2: Rasterize to PNG (1200×630) — the PNG MUST exist before shipping**

OG meta points at `og-image.png`; a missing file = a 404 social card. Try installed
SVG tools first:

```bash
cd /home/wesuuu/Code/trellisbio/marketing/assets
rsvg-convert -w 1200 -h 630 og-image.svg -o og-image.png 2>/dev/null \
  || (command -v inkscape >/dev/null && inkscape og-image.svg --export-type=png --export-filename=og-image.png -w 1200 -h 630) \
  || (command -v magick   >/dev/null && magick -background none -size 1200x630 og-image.svg og-image.png) \
  || (command -v convert  >/dev/null && convert -background none -density 150 -resize 1200x630 og-image.svg og-image.png) \
  || echo "NO_RASTERIZER"
```

**If that prints `NO_RASTERIZER`**, use the guaranteed headless-Chrome path (Chrome is
available in this environment). Wrap the SVG in a sized HTML page and screenshot it:

```bash
cd /home/wesuuu/Code/trellisbio/marketing/assets
printf '<!doctype html><meta charset=utf-8><style>html,body{margin:0}</style>' > _og.html
cat og-image.svg >> _og.html
# Option A — Chrome/Chromium CLI:
( command -v google-chrome || command -v chromium || command -v chromium-browser ) >/dev/null && \
  "$(command -v google-chrome || command -v chromium || command -v chromium-browser)" \
    --headless --no-sandbox --force-device-scale-factor=1 \
    --window-size=1200,630 --screenshot=og-image.png "$(pwd)/_og.html"
rm -f _og.html
```

> If no Chrome CLI binary exists either, drive the **Claude-in-Chrome MCP** during Task 11:
> navigate to `file://…/marketing/assets/_og.html`, resize the window to 1200×630, screenshot,
> and save as `og-image.png`. Do **not** finish the feature with the PNG missing.

- [ ] **Step 3: Verify**

Run: `cd /home/wesuuu/Code/trellisbio/marketing/assets && ls -la og-image.png && file og-image.png`
Expected: file exists, `PNG image data, 1200 x 630`.

- [ ] **Step 4: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/assets/
git commit -m "feat(F-0079): branded OG share image (svg + 1200x630 png)"
```

---

### Task 8: `robots.txt` + `sitemap.xml`

**Files:**
- Create: `marketing/robots.txt`, `marketing/sitemap.xml`

- [ ] **Step 1: Create `marketing/robots.txt`**

```
User-agent: *
Allow: /

Sitemap: https://batchrite.com/sitemap.xml
```

- [ ] **Step 2: Create `marketing/sitemap.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://batchrite.com/</loc></url>
  <url><loc>https://batchrite.com/about</loc></url>
  <url><loc>https://batchrite.com/roadmap</loc></url>
</urlset>
```

- [ ] **Step 3: Verify**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && cat robots.txt && python3 -c "import xml.dom.minidom,pathlib;xml.dom.minidom.parseString(pathlib.Path('sitemap.xml').read_text());print('sitemap OK')"`
Expected: robots prints; `sitemap OK`.

- [ ] **Step 4: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/robots.txt marketing/sitemap.xml
git commit -m "feat(F-0079): robots.txt + sitemap.xml"
```

---

### Task 9: `_headers` (CSP + security + cache)

**Files:**
- Create: `marketing/_headers`

The pages carry 203 inline `style=` attrs + an inline `<style>` and an inline `<script>` per page (the brand-mark injector). The CSP MUST allow inline style+script or layout/logo break. Calendly needs no allowance (top-level nav). Spec §5.6.

- [ ] **Step 1: Create `marketing/_headers`**

```
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: DENY
  Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'

/css/*
  Cache-Control: public, max-age=31536000, immutable

/js/*
  Cache-Control: public, max-age=31536000, immutable

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/favicon.svg
  Cache-Control: public, max-age=604800
```

- [ ] **Step 2: Verify the file parses as plain text (no syntax to compile) and CSP names the inline allowances**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && grep -E "script-src 'self' 'unsafe-inline'" _headers && grep -E "style-src 'self' 'unsafe-inline'" _headers`
Expected: both lines print (CSP allows inline script + style).

- [ ] **Step 3: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/_headers
git commit -m "feat(F-0079): Cloudflare _headers (CSP tolerant of inline style/script, cache, security)"
```

---

### Task 10: `README.md` (deploy + retarget + lineage)

**Files:**
- Create: `marketing/README.md`

- [ ] **Step 1: Create `marketing/README.md`**

````markdown
# Batchrite Marketing Site

Static marketing/sales site for Batchrite. **No build step** — plain HTML/CSS + one
vanilla Web Component. Source wireframes live in `../mockups/sales-wireframes/`
(authoring copy, with the full drag/drop `image-slot.js`); this directory is the
production deploy.

## Local preview

Use Wrangler so `_headers` (the CSP) is actually applied — `npx serve` skips it and
hides CSP breakage. Requires **Node 16.17+**; the version is pinned to avoid v2/v3 CLI
drift:

```bash
npx wrangler@3 pages dev marketing
```

## Deploy (Cloudflare Pages)

- **Direct:** `npx wrangler pages deploy marketing`
- **Git integration:** Framework preset **None**, build command **(empty)**, build
  output directory **`marketing`**.

Custom domain + TLS are configured in the Cloudflare Pages dashboard (Pages → project →
Custom domains). Not done from this repo.

## Retargeting the domain

The base origin `https://batchrite.com` is hardcoded across the canonical/OG meta (4
tags × 3 pages), `sitemap.xml` (3), and `robots.txt` (1) — all occurrences. To change it:

```bash
grep -rl 'https://batchrite.com' marketing/ | xargs sed -i 's#https://batchrite.com#https://NEW-ORIGIN#g'
```

**Two externals the grep above does NOT catch** (different hosts — repoint manually):
- `https://app.batchrite.com` — the nav "Sign in" CTA (the marketing site's only runtime
  link to the app). `grep -rl 'app.batchrite.com' marketing/`.
- `https://calendly.com/batchrite/founding-partner` — every pilot CTA (~4 across the 3
  pages). `grep -rl 'calendly.com/batchrite' marketing/`.

## Brand colors

Hex values in `css/batchrite.css` (`--teal #0A4C5C`, `--green #1DA570`, `--amber
#F59A1A`, `--bone #F4F7F9`) are the canonical brand mark colors, mirrored from
`frontend/src/lib/components/layout/LogoMark.svelte`. On a rebrand, update both
together. (The app's `frontend/src/app.css` uses HSL `@theme` aliases that compute to
slightly different hex — `LogoMark.svelte` is the source of the exact values.)

## Notes

- The brand-mark SVG `<template id="brm-mark">` is duplicated inline in all three pages
  and injected by a small inline script. Editing the mark means touching all three.
  Acceptable at three pages; revisit a build step if the site grows past ~5.
- Deferred to follow-up tasks (see ClickUp F-0079): PostHog analytics, Loops CRM,
  register `?ref=` attribution, public-beta tier, real product screenshots. When PostHog
  lands, its `script-src`/`connect-src` must be added to `_headers`.
````

- [ ] **Step 2: Verify**

Run: `cd /home/wesuuu/Code/trellisbio/marketing && grep -c 'wrangler pages dev\|wrangler pages deploy\|LogoMark.svelte' README.md`
Expected: ≥ 3.

- [ ] **Step 3: Commit**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/README.md
git commit -m "docs(F-0079): marketing/ deploy + domain-retarget + brand-lineage README"
```

---

### Task 11: Full verification pass (browser + audits)

**Files:** none (verification only)

- [ ] **Step 1: Serve under Wrangler (CSP applied)**

```bash
cd /home/wesuuu/Code/trellisbio
npx wrangler@3 pages dev marketing --port 8788
```
(Requires Node 16.17+. `npx` fetches wrangler on first run.)

- [ ] **Step 2: Grep audit (no residue, links clean)**

```bash
cd /home/wesuuu/Code/trellisbio/marketing
echo "cdn-cgi (0):"; grep -rc 'cdn-cgi' *.html
echo "cap .html cross-links (none):"; grep -roE 'href="(Batchrite|About|Roadmap)\.html' *.html || echo none
echo "omelette in shipped js (0):"; grep -c omelette js/image-slot.js
echo "press stubs (0):"; grep -c 'brand-kit.zip' about.html
echo "dangling #press links (0):"; grep -rc 'href="[^"]*#press"' *.html | grep -v ':0' || echo "none"
echo "css/js root-absolute:"; grep -hoE '(href|src)="/?(css|js)/[^"]*"' *.html | sort -u
```
Expected: cdn-cgi `0`/page; `none`; `0`; `0`; `none`; every css/js path begins with
`/css/` or `/js/` (root-absolute, uniform with `/favicon.svg`).

- [ ] **Step 3: Browser QA via the qa-verify agent**

Load `http://localhost:8788/`, `/about`, `/roadmap`. Confirm for each:
- Full CSS applied, fonts loaded, **brand logo renders** (inline script ran under CSP).
- **Zero console errors / zero CSP violations** (no `window.omelette`, no sidecar 404).
- Nav cross-links work; `#features/#beta/#trust/#faq/#product/#modalities/#values/#who` anchors scroll.
- All Calendly CTAs open `founding-partner` in a new tab; "Sign in" → `app.batchrite.com`.
- All `mailto:` links open a composer with a real `@batchrite.com` address.
- About `<image-slot>` placeholders render (circle avatars + founder portrait), no blanks.
- About press section is gone (no "Press & contact" heading, no download stubs).
- **Clean URLs**: navigating to `/about/` (trailing slash) redirects to `/about` and the
  page renders with CSS intact (confirms root-absolute `/css/` paths survive the trailing
  slash). `/about` and `/roadmap` both load directly.
- Responsive: spot-check mobile (≤480px) and desktop.

- [ ] **Step 4: Lighthouse**

Run Lighthouse (Chrome DevTools or `npx lighthouse http://localhost:8788/ --only-categories=performance,accessibility,seo,best-practices`). Targets: perf ≥ 95, a11y ≥ 95, SEO ≥ 95. Record scores; fix regressions (most likely: image dimensions, color contrast, or a missing `lang`/alt — address in the source HTML and re-commit).

- [ ] **Step 5: Final commit (if QA produced fixes)**

```bash
cd /home/wesuuu/Code/trellisbio
git add marketing/
git commit -m "fix(F-0079): browser/Lighthouse QA fixes"
```

---

## Self-Review (spec coverage)

- §5.1 directory layout → Tasks 1, 2, 5–10 ✓
- §5.2 URL rewrite + CTA targets + press removal → Task 3 ✓
- §5.3 slim image-slot (full attrs, shadow styles, no fetch) → Task 2 ✓
- §5.4 decode emails + visible text + remove decode scripts → Task 4 ✓
- §5.5 SEO/OG/favicon/og-image → Tasks 5, 6, 7 ✓
- §5.6 _headers CSP + cache; robots/sitemap → Tasks 8, 9 ✓
- §5.1 commit mockups source → Task 0 ✓
- README (deploy, retarget, brand lineage, brm-mark note, PostHog CSP hand-off) → Task 10 ✓
- §6 verification (wrangler dev, grep, browser, Lighthouse) → Task 11 ✓
- §3 non-goals (PostHog/Loops/ref/tier/screenshots/domain) → not implemented, documented in README ✓
