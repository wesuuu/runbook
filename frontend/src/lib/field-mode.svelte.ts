/**
 * Reactive field mode store.
 * Manages the full lifecycle: activation, lock/unlock, inactivity, expiry, and teardown.
 */

import { encrypt, decrypt, deriveSessionKey, encryptWithKey, decryptWithKey } from '$lib/crypto';
import {
    saveSession,
    getSession,
    deleteSession,
    getAllSessions,
    enqueueAction,
    getUnsynced,
    getUnsyncedCount,
    type FieldSession,
    type QueuedAction,
} from '$lib/offline-db';

// --- Types ---

export interface RunSnapshot {
    run_id: string;
    run_name: string;
    run_status: string;
    graph: Record<string, unknown>;
    execution_data: Record<string, unknown>;
    role_assignments: Array<{
        id: string;
        lane_node_id: string;
        role_name: string;
        user_id: string;
        user_name: string | null;
    }>;
    unit_op_definitions: Record<string, unknown>;
}

type FieldModeState = 'inactive' | 'active' | 'locked';

// --- Reactive state ---

let state = $state<FieldModeState>('inactive');
let activeRunId = $state<string | null>(null);
let activeRunName = $state<string | null>(null);
let offlineToken = $state<string | null>(null);
let expiresAt = $state<Date | null>(null);
let queueCount = $state(0);
let runSnapshot = $state<RunSnapshot | null>(null);

// Derived key held in memory — wiped on lock
let sessionKey: CryptoKey | null = null;
let sessionSalt: string | null = null;

// Inactivity tracking
let inactivityTimer: ReturnType<typeof setTimeout> | null = null;
const INACTIVITY_TIMEOUT_MS = 60 * 60 * 1000; // 1 hour

// Expiry warning thresholds (in ms)
const EXPIRY_THRESHOLDS = [
    { ms: 48 * 60 * 60 * 1000, level: 'amber' as const },
    { ms: 24 * 60 * 60 * 1000, level: 'amber' as const },
    { ms: 6 * 60 * 60 * 1000, level: 'red' as const },
    { ms: 1 * 60 * 60 * 1000, level: 'critical' as const },
];

// --- Getters ---

export function getFieldModeState(): FieldModeState {
    return state;
}

export function isFieldModeActive(): boolean {
    return state === 'active' || state === 'locked';
}

export function isFieldModeLocked(): boolean {
    return state === 'locked';
}

export function getActiveRunId(): string | null {
    return activeRunId;
}

export function getActiveRunName(): string | null {
    return activeRunName;
}

export function getOfflineToken(): string | null {
    return offlineToken;
}

export function getExpiresAt(): Date | null {
    return expiresAt;
}

export function getQueueCount(): number {
    return queueCount;
}

export function getRunSnapshot(): RunSnapshot | null {
    return runSnapshot;
}

export type ExpiryWarningLevel = 'none' | 'amber' | 'red' | 'critical';

export function getExpiryWarningLevel(): ExpiryWarningLevel {
    if (!expiresAt) return 'none';
    const remaining = expiresAt.getTime() - Date.now();
    if (remaining <= 0) return 'critical';
    for (const threshold of EXPIRY_THRESHOLDS) {
        if (remaining <= threshold.ms) return threshold.level;
    }
    return 'none';
}

export function getTimeRemaining(): string {
    if (!expiresAt) return '';
    const remaining = expiresAt.getTime() - Date.now();
    if (remaining <= 0) return 'Expired';
    const hours = Math.floor(remaining / (60 * 60 * 1000));
    const minutes = Math.floor((remaining % (60 * 60 * 1000)) / (60 * 1000));
    if (hours > 24) {
        const days = Math.floor(hours / 24);
        return `${days}d ${hours % 24}h remaining`;
    }
    return `${hours}h ${minutes}m remaining`;
}

// --- Activation ---

export async function activateFieldMode(
    password: string,
    snapshot: RunSnapshot,
    token: string,
    expires: string,
    userId: string,
    userEmail: string,
): Promise<void> {
    // Encrypt the snapshot with the user's password
    const encrypted = await encrypt(snapshot, password);

    // Save session to IndexedDB
    const session: FieldSession = {
        run_id: snapshot.run_id,
        run_name: snapshot.run_name,
        user_id: userId,
        user_email: userEmail,
        offline_token: token,
        expires_at: expires,
        salt: encrypted.salt,
        encrypted_data: { ciphertext: encrypted.ciphertext, iv: encrypted.iv },
        created_at: new Date().toISOString(),
    };
    await saveSession(session);

    // Derive key and keep in memory
    sessionSalt = encrypted.salt;
    sessionKey = await deriveSessionKey(password, sessionSalt);

    // Set reactive state
    activeRunId = snapshot.run_id;
    activeRunName = snapshot.run_name;
    offlineToken = token;
    expiresAt = new Date(expires);
    runSnapshot = snapshot;
    state = 'active';
    queueCount = await getUnsyncedCount(snapshot.run_id);

    resetInactivityTimer();
}

/** Restore field mode from IndexedDB (e.g., on page reload). Returns true if restored. */
export async function restoreFieldMode(runId: string, password: string): Promise<boolean> {
    const session = await getSession(runId);
    if (!session) return false;

    // Check expiry
    if (new Date(session.expires_at) <= new Date()) {
        // Expired — don't delete session, queue may still have items
        return false;
    }

    // Derive key and decrypt
    sessionSalt = session.salt;
    sessionKey = await deriveSessionKey(password, sessionSalt);
    const snapshot = await decryptWithKey<RunSnapshot>(
        session.encrypted_data.ciphertext,
        session.encrypted_data.iv,
        sessionKey,
    );
    if (!snapshot) {
        sessionKey = null;
        sessionSalt = null;
        return false;
    }

    activeRunId = session.run_id;
    activeRunName = session.run_name;
    offlineToken = session.offline_token;
    expiresAt = new Date(session.expires_at);
    runSnapshot = snapshot;
    state = 'active';
    queueCount = await getUnsyncedCount(session.run_id);

    resetInactivityTimer();
    return true;
}

/** Check if there's an active (non-expired) session for any run. */
export async function hasActiveSession(): Promise<{ runId: string; runName: string; userEmail: string } | null> {
    const sessions = await getAllSessions();
    for (const s of sessions) {
        if (new Date(s.expires_at) > new Date()) {
            return { runId: s.run_id, runName: s.run_name, userEmail: s.user_email };
        }
    }
    return null;
}

// --- Locking ---

export function lockSession(): void {
    if (state !== 'active') return;
    // Wipe derived key from memory
    sessionKey = null;
    state = 'locked';
    clearInactivityTimer();
}

export async function unlockSession(password: string): Promise<boolean> {
    if (state !== 'locked' || !activeRunId || !sessionSalt) return false;

    const session = await getSession(activeRunId);
    if (!session) return false;

    sessionKey = await deriveSessionKey(password, sessionSalt);
    const snapshot = await decryptWithKey<RunSnapshot>(
        session.encrypted_data.ciphertext,
        session.encrypted_data.iv,
        sessionKey,
    );
    if (!snapshot) {
        sessionKey = null;
        return false;
    }

    runSnapshot = snapshot;
    state = 'active';
    resetInactivityTimer();
    return true;
}

// --- Inactivity Timer ---

function resetInactivityTimer(): void {
    clearInactivityTimer();
    inactivityTimer = setTimeout(() => {
        if (state === 'active') lockSession();
    }, INACTIVITY_TIMEOUT_MS);
}

function clearInactivityTimer(): void {
    if (inactivityTimer) {
        clearTimeout(inactivityTimer);
        inactivityTimer = null;
    }
}

/** Call on any user interaction to reset the inactivity timer. */
export function recordActivity(): void {
    if (state === 'active') {
        resetInactivityTimer();
    }
}

// --- Queue Operations ---

export async function queueAction(
    action: Omit<QueuedAction, 'id' | 'queued_at' | 'synced' | 'run_id' | 'run_name'>,
): Promise<void> {
    if (!activeRunId || !activeRunName) return;
    await enqueueAction({
        ...action,
        run_id: activeRunId,
        run_name: activeRunName,
        queued_at: new Date().toISOString(),
        synced: false,
    });
    queueCount = await getUnsyncedCount(activeRunId);
}

export async function refreshQueueCount(): Promise<void> {
    if (activeRunId) {
        queueCount = await getUnsyncedCount(activeRunId);
    }
}

// --- Execution Data Updates (in-memory, persisted to encrypted store) ---

export async function updateExecutionData(stepId: string, data: Record<string, unknown>): Promise<void> {
    if (!runSnapshot || !sessionKey || !activeRunId) return;

    const updated = { ...runSnapshot };
    updated.execution_data = {
        ...updated.execution_data,
        [stepId]: data,
    };
    runSnapshot = updated;

    // Re-encrypt and save
    const session = await getSession(activeRunId);
    if (session && sessionKey) {
        const enc = await encryptWithKey(updated, sessionKey);
        session.encrypted_data = enc;
        await saveSession(session);
    }
}

// --- Teardown ---

export async function endFieldMode(wipeQueue = false): Promise<void> {
    if (activeRunId) {
        await deleteSession(activeRunId);
        if (wipeQueue) {
            // Delete all queue items for this run (including unsynced)
            const items = await getUnsynced(activeRunId);
            const { deleteQueueItem } = await import('$lib/offline-db');
            for (const item of items) {
                if (item.id !== undefined) await deleteQueueItem(item.id);
            }
        }
    }

    // Reset all state
    state = 'inactive';
    activeRunId = null;
    activeRunName = null;
    offlineToken = null;
    expiresAt = null;
    queueCount = 0;
    runSnapshot = null;
    sessionKey = null;
    sessionSalt = null;
    clearInactivityTimer();
}

// --- Initialization (call on app startup to detect existing sessions) ---

export async function initFieldMode(): Promise<void> {
    const existing = await hasActiveSession();
    if (existing) {
        // There's a session but we don't have the password — go to locked state
        activeRunId = existing.runId;
        activeRunName = existing.runName;
        const session = await getSession(existing.runId);
        if (session) {
            offlineToken = session.offline_token;
            expiresAt = new Date(session.expires_at);
            sessionSalt = session.salt;
        }
        state = 'locked';
        queueCount = await getUnsyncedCount(existing.runId);
    }
}
