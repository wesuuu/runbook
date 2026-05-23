/**
 * Step-level deep-link helper.
 *
 * Producers stamp `data-step-id="<id>"` on the DOM node for each step;
 * `focusStep(id)` scrolls the matching node into view and applies a
 * brief outline-fade highlight. Honors `prefers-reduced-motion: reduce`
 * (instant scroll, no animation). Silent no-op when no element matches.
 *
 * The associated CSS rule (`.step-deeplink-target`) is injected into
 * `document.head` on first call so consumers don't have to remember to
 * ship it. The `step_id` shape (`^[A-Za-z0-9_-]{1,64}$`) is enforced
 * upstream at the backend resolver and at each frontend hash parse;
 * `CSS.escape` here is a final belt-and-suspenders.
 */

const STYLE_ID = 'step-deeplink-style';
const HIGHLIGHT_CLASS = 'step-deeplink-target';
const HIGHLIGHT_MS = 1500;

function ensureStyle(): void {
    if (typeof document === 'undefined') return;
    if (document.head.querySelector(`style[data-step-deeplink]`)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.setAttribute('data-step-deeplink', '');
    style.textContent = `
.${HIGHLIGHT_CLASS} {
    animation: stepDeepLinkPulse ${HIGHLIGHT_MS}ms ease-out;
    border-radius: 6px;
}
@keyframes stepDeepLinkPulse {
    0%   { box-shadow: 0 0 0 0 hsl(var(--ring) / 0); background-color: hsl(var(--ring) / 0); }
    20%  { box-shadow: 0 0 0 4px hsl(var(--ring) / 0.55); background-color: hsl(var(--ring) / 0.10); }
    100% { box-shadow: 0 0 0 0 hsl(var(--ring) / 0); background-color: hsl(var(--ring) / 0); }
}
@media (prefers-reduced-motion: reduce) {
    .${HIGHLIGHT_CLASS} { animation: none; box-shadow: none; background: none; }
}
`.trim();
    document.head.appendChild(style);
}

function prefersReducedMotion(): boolean {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export async function focusStep(stepId: string): Promise<void> {
    if (typeof document === 'undefined') return;
    ensureStyle();
    const selector = `[data-step-id="${CSS.escape(stepId)}"]`;
    const el = document.querySelector(selector) as HTMLElement | null;
    if (!el) return;

    const reduceMotion = prefersReducedMotion();
    el.scrollIntoView({
        behavior: reduceMotion ? 'auto' : 'smooth',
        block: 'center',
    });
    if (reduceMotion) return;

    el.classList.remove(HIGHLIGHT_CLASS);
    void el.offsetWidth;
    el.classList.add(HIGHLIGHT_CLASS);
    window.setTimeout(() => {
        el.classList.remove(HIGHLIGHT_CLASS);
    }, HIGHLIGHT_MS);
}
