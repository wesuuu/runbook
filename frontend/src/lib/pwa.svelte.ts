/**
 * Reactive online/offline connectivity state.
 * Listens to browser online/offline events and exposes a reactive `isOnline` getter.
 */

import { OFFLINE_ENABLED } from '$lib/feature-flags';

let online = $state(typeof navigator !== 'undefined' ? navigator.onLine : true);

function handleOnline() {
    online = true;
}

function handleOffline() {
    online = false;
}

/** Call once on app mount to start listening to connectivity events. */
export function initConnectivity(): void {
    if (!OFFLINE_ENABLED) return;
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    // Sync initial state
    online = navigator.onLine;
}

/** Clean up listeners if needed. */
export function destroyConnectivity(): void {
    window.removeEventListener('online', handleOnline);
    window.removeEventListener('offline', handleOffline);
}

export function isOnline(): boolean {
    return online;
}
