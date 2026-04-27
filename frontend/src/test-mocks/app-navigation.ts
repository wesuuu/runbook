// Test-only stub for $app/navigation. Vitest does not run through SvelteKit,
// so the real $app/* virtual modules are unavailable. This stub is aliased
// in vitest.config.ts and overridden per-test with vi.mock() as needed.
export const goto = (..._args: unknown[]): Promise<void> => Promise.resolve();
export const beforeNavigate = (_fn: unknown): void => {};
export const afterNavigate = (_fn: unknown): void => {};
export const invalidate = (..._args: unknown[]): Promise<void> => Promise.resolve();
export const invalidateAll = (): Promise<void> => Promise.resolve();
export const preloadCode = (..._args: unknown[]): Promise<void> => Promise.resolve();
export const preloadData = (..._args: unknown[]): Promise<unknown> => Promise.resolve();
export const pushState = (..._args: unknown[]): void => {};
export const replaceState = (..._args: unknown[]): void => {};
