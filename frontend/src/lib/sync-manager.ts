/**
 * Sync manager: drains the action queue when connectivity is restored.
 *
 * - Registers Background Sync API (Chrome/Android)
 * - Falls back to `online` + `visibilitychange` events (Safari/iPad)
 * - Batches actions per run for the /sync/offline-queue endpoint
 */

import { getUnsynced, markSynced, markSyncError, getOrphanedActions } from '$lib/offline-db';
import { getOfflineToken, refreshQueueCount, isFieldModeActive, getActiveRunId } from '$lib/field-mode.svelte';
import { getToken } from '$lib/auth.svelte';
import { API_BASE } from '$lib/config';
import { OFFLINE_ENABLED } from '$lib/feature-flags';

const SYNC_TAG = 'runbook-offline-sync';
let syncing = false;
let initialized = false;

/** Perform a sync POST using either the offline token or the normal auth token. */
async function syncBatch(runId: string, actions: Array<Record<string, unknown>>): Promise<{
    total: number;
    succeeded: number;
    failed: number;
    results: Array<{ index: number; success: boolean; error?: string }>;
}> {
    const token = isFieldModeActive() ? getOfflineToken() : getToken();
    if (!token) throw new Error('No auth token available');

    const response = await fetch(`${API_BASE}/sync/offline-queue/${runId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ actions }),
    });

    if (!response.ok) {
        const detail = await response.text();
        throw new Error(`Sync failed (${response.status}): ${detail}`);
    }
    return response.json();
}

/** Drain all unsynced actions, grouped by run_id. */
export async function drainQueue(): Promise<{ synced: number; failed: number }> {
    if (!OFFLINE_ENABLED) return { synced: 0, failed: 0 };
    if (syncing) return { synced: 0, failed: 0 };
    syncing = true;
    let totalSynced = 0;
    let totalFailed = 0;

    try {
        const grouped = await getOrphanedActions();

        for (const [runId, items] of grouped) {
            // Build the actions array for the batch endpoint
            const batchActions = items.map((item) => {
                const action: Record<string, unknown> = { action_type: item.action_type };
                if (item.step_id) action.step_id = item.step_id;
                if (item.image_data) action.image_data = item.image_data;
                if (item.image_filename) action.image_filename = item.image_filename;
                if (item.parameter_tags) action.parameter_tags = item.parameter_tags;
                if (item.image_id) action.image_id = item.image_id;
                if (item.values) action.values = item.values;
                return action;
            });

            try {
                const result = await syncBatch(runId, batchActions);

                // Mark individual items based on result
                for (let i = 0; i < items.length; i++) {
                    const item = items[i];
                    const actionResult = result.results[i];
                    if (item.id === undefined) continue;

                    if (actionResult?.success) {
                        await markSynced(item.id);
                        totalSynced++;
                    } else {
                        await markSyncError(item.id, actionResult?.error ?? 'Unknown error');
                        totalFailed++;
                    }
                }
            } catch (err) {
                // Entire batch failed — mark all with error
                for (const item of items) {
                    if (item.id !== undefined) {
                        await markSyncError(item.id, err instanceof Error ? err.message : 'Sync failed');
                    }
                }
                totalFailed += items.length;
            }
        }
    } finally {
        syncing = false;
        await refreshQueueCount();
    }

    return { synced: totalSynced, failed: totalFailed };
}

/** Handle online event — attempt to drain queue. */
function handleOnline() {
    drainQueue().catch(console.error);
}

/** Handle visibility change — sync when app comes to foreground while online. */
function handleVisibilityChange() {
    if (document.visibilityState === 'visible' && navigator.onLine) {
        drainQueue().catch(console.error);
    }
}

/** Register Background Sync API if available (Chrome/Android). */
async function registerBackgroundSync(): Promise<void> {
    if (!('serviceWorker' in navigator)) return;
    try {
        const reg = await navigator.serviceWorker.ready;
        if ('sync' in reg) {
            await (reg as any).sync.register(SYNC_TAG);
        }
    } catch {
        // Background Sync not supported — fallback events handle it
    }
}

/** Initialize the sync manager. Call once on app startup. */
export function initSyncManager(): void {
    if (!OFFLINE_ENABLED) return;
    if (initialized) return;
    initialized = true;

    window.addEventListener('online', handleOnline);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    // Register Background Sync
    registerBackgroundSync().catch(console.error);

    // Attempt initial drain if online
    if (navigator.onLine) {
        drainQueue().catch(console.error);
    }
}

/** Clean up listeners. */
export function destroySyncManager(): void {
    window.removeEventListener('online', handleOnline);
    document.removeEventListener('visibilitychange', handleVisibilityChange);
    initialized = false;
}

/** Check if a sync is currently in progress. */
export function isSyncing(): boolean {
    return syncing;
}

/** Manually trigger a sync (e.g., from "Sync Now" button). */
export async function syncNow(): Promise<{ synced: number; failed: number }> {
    if (!OFFLINE_ENABLED) return { synced: 0, failed: 0 };
    return drainQueue();
}
