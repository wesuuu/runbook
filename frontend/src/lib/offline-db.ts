/**
 * IndexedDB wrapper for offline field mode.
 *
 * Two object stores:
 *   - `field-sessions`: encrypted run session data (keyed by run_id)
 *   - `action-queue`:   unencrypted queued actions (auto-increment key)
 *
 * The action-queue persists independently of the session — orphaned items
 * are recoverable on next normal login.
 */

const DB_NAME = 'batchrite_offline';
const DB_VERSION = 1;
const SESSIONS_STORE = 'field-sessions';
const QUEUE_STORE = 'action-queue';

export interface FieldSession {
    run_id: string;
    run_name: string;
    user_id: string;
    user_email: string;
    offline_token: string;
    expires_at: string;
    /** Base64-encoded salt used for PBKDF2 key derivation */
    salt: string;
    /** Encrypted run data (ciphertext + iv) */
    encrypted_data: { ciphertext: string; iv: string };
    created_at: string;
}

export interface QueuedAction {
    id?: number;
    run_id: string;
    run_name: string;
    action_type: 'image_upload' | 'parameter_tag' | 'manual_values';
    /** Step node ID */
    step_id?: string;
    /** Base64-encoded image data for image_upload */
    image_data?: string;
    image_filename?: string;
    parameter_tags?: string[];
    image_id?: string;
    /** Manual values for manual_values actions */
    values?: Record<string, unknown>;
    /** Timestamp of when the action was queued */
    queued_at: string;
    /** Whether this action has been synced */
    synced: boolean;
    /** Error from last sync attempt, if any */
    sync_error?: string;
}

function openDb(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
        request.onupgradeneeded = (event) => {
            const db = (event.target as IDBOpenDBRequest).result;
            if (!db.objectStoreNames.contains(SESSIONS_STORE)) {
                db.createObjectStore(SESSIONS_STORE, { keyPath: 'run_id' });
            }
            if (!db.objectStoreNames.contains(QUEUE_STORE)) {
                const store = db.createObjectStore(QUEUE_STORE, {
                    keyPath: 'id',
                    autoIncrement: true,
                });
                store.createIndex('run_id', 'run_id', { unique: false });
                store.createIndex('synced', 'synced', { unique: false });
            }
        };
    });
}

function tx<T>(
    storeName: string,
    mode: IDBTransactionMode,
    fn: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
    return openDb().then(
        (db) =>
            new Promise((resolve, reject) => {
                const transaction = db.transaction(storeName, mode);
                const store = transaction.objectStore(storeName);
                const request = fn(store);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            }),
    );
}

// --- Field Sessions ---

export async function saveSession(session: FieldSession): Promise<void> {
    await tx(SESSIONS_STORE, 'readwrite', (store) => store.put(session));
}

export async function getSession(runId: string): Promise<FieldSession | undefined> {
    return tx(SESSIONS_STORE, 'readonly', (store) => store.get(runId));
}

export async function deleteSession(runId: string): Promise<void> {
    await tx(SESSIONS_STORE, 'readwrite', (store) => store.delete(runId));
}

export async function getAllSessions(): Promise<FieldSession[]> {
    return tx(SESSIONS_STORE, 'readonly', (store) => store.getAll());
}

// --- Action Queue ---

export async function enqueueAction(action: Omit<QueuedAction, 'id'>): Promise<number> {
    return tx(QUEUE_STORE, 'readwrite', (store) => store.add(action)) as Promise<number>;
}

export async function getUnsynced(runId?: string): Promise<QueuedAction[]> {
    const db = await openDb();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(QUEUE_STORE, 'readonly');
        const store = transaction.objectStore(QUEUE_STORE);
        // Boolean values are not valid IDB keys, so we scan all and filter
        const request = store.getAll();
        request.onsuccess = () => {
            let items = (request.result as QueuedAction[]).filter((a) => !a.synced);
            if (runId) items = items.filter((a) => a.run_id === runId);
            resolve(items);
        };
        request.onerror = () => reject(request.error);
    });
}

export async function markSynced(id: number): Promise<void> {
    const db = await openDb();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(QUEUE_STORE, 'readwrite');
        const store = transaction.objectStore(QUEUE_STORE);
        const getReq = store.get(id);
        getReq.onsuccess = () => {
            const item = getReq.result;
            if (item) {
                item.synced = true;
                item.sync_error = undefined;
                const putReq = store.put(item);
                putReq.onsuccess = () => resolve();
                putReq.onerror = () => reject(putReq.error);
            } else {
                resolve();
            }
        };
        getReq.onerror = () => reject(getReq.error);
    });
}

export async function markSyncError(id: number, error: string): Promise<void> {
    const db = await openDb();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(QUEUE_STORE, 'readwrite');
        const store = transaction.objectStore(QUEUE_STORE);
        const getReq = store.get(id);
        getReq.onsuccess = () => {
            const item = getReq.result;
            if (item) {
                item.sync_error = error;
                const putReq = store.put(item);
                putReq.onsuccess = () => resolve();
                putReq.onerror = () => reject(putReq.error);
            } else {
                resolve();
            }
        };
        getReq.onerror = () => reject(getReq.error);
    });
}

export async function deleteQueueItem(id: number): Promise<void> {
    await tx(QUEUE_STORE, 'readwrite', (store) => store.delete(id));
}

export async function clearSyncedActions(runId: string): Promise<void> {
    const items = await getUnsynced();
    const db = await openDb();
    const transaction = db.transaction(QUEUE_STORE, 'readwrite');
    const store = transaction.objectStore(QUEUE_STORE);
    // Delete all synced items for this run
    const allReq = store.getAll();
    return new Promise((resolve, reject) => {
        allReq.onsuccess = () => {
            const all = allReq.result as QueuedAction[];
            for (const item of all) {
                if (item.run_id === runId && item.synced && item.id !== undefined) {
                    store.delete(item.id);
                }
            }
            resolve();
        };
        allReq.onerror = () => reject(allReq.error);
    });
}

/** Get all unsynced actions grouped by run (for orphan recovery on dashboard). */
export async function getOrphanedActions(): Promise<Map<string, QueuedAction[]>> {
    const items = await getUnsynced();
    const grouped = new Map<string, QueuedAction[]>();
    for (const item of items) {
        const list = grouped.get(item.run_id) ?? [];
        list.push(item);
        grouped.set(item.run_id, list);
    }
    return grouped;
}

/** Count all unsynced items. */
export async function getUnsyncedCount(runId?: string): Promise<number> {
    const items = await getUnsynced(runId);
    return items.length;
}
