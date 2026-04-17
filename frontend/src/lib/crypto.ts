/**
 * Web Crypto API helpers for offline field mode session encryption.
 * Uses PBKDF2 for key derivation and AES-256-GCM for authenticated encryption.
 */

const PBKDF2_ITERATIONS = 100_000;
const SALT_BYTES = 16;
const IV_BYTES = 12;
const KEY_BITS = 256;

/** Derive an AES-256-GCM key from a password + salt using PBKDF2. */
async function deriveKey(password: string, salt: Uint8Array): Promise<CryptoKey> {
    const encoder = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey(
        'raw',
        encoder.encode(password),
        'PBKDF2',
        false,
        ['deriveKey'],
    );
    return crypto.subtle.deriveKey(
        { name: 'PBKDF2', salt, iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
        keyMaterial,
        { name: 'AES-GCM', length: KEY_BITS },
        false,
        ['encrypt', 'decrypt'],
    );
}

export interface EncryptedPayload {
    /** Base64-encoded ciphertext */
    ciphertext: string;
    /** Base64-encoded IV (12 bytes) */
    iv: string;
    /** Base64-encoded salt (16 bytes) */
    salt: string;
}

function toBase64(buf: ArrayBuffer): string {
    return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

function fromBase64(b64: string): Uint8Array {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return arr;
}

/** Encrypt a JSON-serializable value with AES-256-GCM. Returns ciphertext + IV + salt. */
export async function encrypt(data: unknown, password: string): Promise<EncryptedPayload> {
    const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
    const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
    const key = await deriveKey(password, salt);
    const encoded = new TextEncoder().encode(JSON.stringify(data));
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
    return {
        ciphertext: toBase64(ciphertext),
        iv: toBase64(iv),
        salt: toBase64(salt),
    };
}

/** Decrypt an AES-256-GCM payload back to the original value. Returns null on wrong password. */
export async function decrypt<T = unknown>(payload: EncryptedPayload, password: string): Promise<T | null> {
    try {
        const salt = fromBase64(payload.salt);
        const iv = fromBase64(payload.iv);
        const ciphertext = fromBase64(payload.ciphertext);
        const key = await deriveKey(password, salt);
        const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
        const json = new TextDecoder().decode(decrypted);
        return JSON.parse(json) as T;
    } catch {
        // Wrong password or corrupted data
        return null;
    }
}

/**
 * Derive a CryptoKey from password + existing salt.
 * Kept in memory during an active field session; wiped on lock/teardown.
 */
export async function deriveSessionKey(password: string, saltB64: string): Promise<CryptoKey> {
    return deriveKey(password, fromBase64(saltB64));
}

/** Encrypt with an existing derived key (avoids re-deriving for repeated writes). */
export async function encryptWithKey(data: unknown, key: CryptoKey): Promise<{ ciphertext: string; iv: string }> {
    const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
    const encoded = new TextEncoder().encode(JSON.stringify(data));
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
    return { ciphertext: toBase64(ciphertext), iv: toBase64(iv) };
}

/** Decrypt with an existing derived key. */
export async function decryptWithKey<T = unknown>(
    ciphertext: string,
    ivB64: string,
    key: CryptoKey,
): Promise<T | null> {
    try {
        const iv = fromBase64(ivB64);
        const ct = fromBase64(ciphertext);
        const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct);
        return JSON.parse(new TextDecoder().decode(decrypted)) as T;
    } catch {
        return null;
    }
}
