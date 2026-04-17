export const PAGE_MS = 250;
export const BLOCK_MS = 220;
export const LIST_MS = 200;

export function prefersReducedMotion(): boolean {
    const mm = (globalThis as { matchMedia?: (q: string) => { matches: boolean } }).matchMedia;
    if (typeof mm !== 'function') return false;
    return mm('(prefers-reduced-motion: reduce)').matches;
}

export const pageDuration = (): number =>
    prefersReducedMotion() ? 0 : PAGE_MS;
export const blockDuration = (): number =>
    prefersReducedMotion() ? 0 : BLOCK_MS;
export const listDuration = (): number =>
    prefersReducedMotion() ? 0 : LIST_MS;
