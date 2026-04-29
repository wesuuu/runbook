/**
 * Runtime feature flags. Read from Vite env vars at build time. Flags must be
 * cheap to read everywhere — keep this file dependency-free.
 *
 * TD-0082: Offline/PWA stack is gated behind OFFLINE_ENABLED. Default off.
 * Re-enabling means flipping VITE_OFFLINE_ENABLED on the frontend and
 * BATCHRITE_FEATURES__OFFLINE_MODE__ENABLED on the backend.
 */

export const OFFLINE_ENABLED: boolean =
    import.meta.env.VITE_OFFLINE_ENABLED === 'true';
