import { API_BASE } from '$lib/config';
import { syncThemeFromServer } from '$lib/theme.svelte';
import { canManageEquipmentLifecycle } from '$lib/permissions/equipment';
import { acceptTos as apiAcceptTos } from './legal-api';

type OrgRole = 'ADMIN' | 'BILLING' | 'MEMBER' | 'PROTOCOL_APPROVER' | 'SITE_MANAGER';

interface ManagedSiteEntry {
    grant_id?: string;
    site: { id: string; [key: string]: unknown };
}

interface User {
    id: string;
    email: string;
    full_name: string | null;
    job_title: string | null;
    avatar_url: string | null;
    signature_initials_url?: string | null;
    signature_full_url?: string | null;
    preferences: Record<string, string>;
    is_active: boolean;
    email_verified: boolean;
    tos_accepted_at: string | null;
    tos_version: string | null;
    tos_current: boolean;
}

interface Org {
    id: string;
    name: string;
    subscription_tier: string;
    created_at: string;
    updated_at: string;
}

let user = $state<User | null>(null);
let token = $state<string | null>(localStorage.getItem('auth_token'));
let currentOrg = $state<Org | null>(null);
let orgs = $state<Org[]>([]);
let initialized = $state(false);
let currentOrgRoles = $state<OrgRole[]>([]);
let managedSiteIds = $state<string[]>([]);

export function getToken(): string | null {
    return token;
}

export function isAuthenticated(): boolean {
    return token !== null && user !== null;
}

export function getUser(): User | null {
    return user;
}

export function getCurrentOrg(): Org | null {
    return currentOrg;
}

export function getOrgs(): Org[] {
    return orgs;
}

export function isInitialized(): boolean {
    return initialized;
}

export function getCurrentOrgRoles(): OrgRole[] {
    return currentOrgRoles;
}

export function getManagedSiteIds(): string[] {
    return managedSiteIds;
}

/**
 * Refresh the calling user's per-site SITE_MANAGER grants for the current
 * org. Drives the `canManageSite()` helper used by equipment-lifecycle and
 * site-management UI (F-0088 decision 4).
 */
export async function refreshManagedSites(): Promise<void> {
    if (!token) return;
    try {
        const res = await authFetch<ManagedSiteEntry[]>('GET', '/users/me/managed-sites');
        managedSiteIds = Array.isArray(res) ? res.map((m) => m.site.id) : [];
    } catch {
        // Best-effort — leave previous value alone (could be offline).
    }
}

/**
 * Refresh the calling user's roles for the currently-selected org by
 * scanning the org's member list. Mirrors the inline pattern used on the
 * settings page. Safe to call repeatedly; no-ops if no org is selected.
 */
export async function refreshCurrentOrgRoles(): Promise<void> {
    if (!token || !user || !currentOrg) {
        currentOrgRoles = [];
        return;
    }
    try {
        const members = await authFetch<Array<{user_id: string; roles?: string[]}>>(
            'GET',
            `/iam/organizations/${currentOrg.id}/members`,
        );
        const me = members.find((m) => m.user_id === user!.id);
        currentOrgRoles = ((me?.roles ?? []) as OrgRole[]);
    } catch {
        // Best-effort
    }
}

/**
 * Returns true if the current user can edit regulated metadata
 * (equipment lifecycle, site-scoped objects) on the given site. ADMIN
 * bypasses; SITE_MANAGER requires a grant on the site.
 */
export function canManageSite(siteId: string): boolean {
    return canManageEquipmentLifecycle({
        roles: currentOrgRoles,
        managedSiteIds,
        siteId,
    });
}

export function getUserPreferences(): Record<string, string> {
    return user?.preferences ?? {};
}

export function isEmailVerified(): boolean {
    return user?.email_verified ?? false;
}

export function isTosCurrent(): boolean {
    return user?.tos_current === true;
}

export async function acceptTos(): Promise<void> {
    const response = (await apiAcceptTos()) as Partial<User>;
    if (user) {
        user = { ...user, ...response };
    }
}

export async function refreshUser(): Promise<void> {
    if (!token) return;
    try {
        user = await authFetch<User>('GET', '/auth/me');
        cacheAuthData();
    } catch {
        // ignore — keep existing data (could be offline)
    }
}

async function authFetch<T>(method: string, endpoint: string, body?: unknown): Promise<T> {
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const config: RequestInit = { method, headers };
    if (body) {
        config.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${endpoint}`, config);

    if (!response.ok) {
        let message = 'An error occurred';
        try {
            const err = await response.json();
            message = err.detail || err.message || message;
        } catch {
            // ignore
        }
        throw new Error(message);
    }

    if (response.status === 204) return {} as T;
    return response.json();
}

/** Cache user and org data to localStorage for offline resilience. */
function cacheAuthData(): void {
    if (user) localStorage.setItem('cached_user', JSON.stringify(user));
    if (orgs.length > 0) localStorage.setItem('cached_orgs', JSON.stringify(orgs));
    if (currentOrg) localStorage.setItem('cached_current_org', JSON.stringify(currentOrg));
    syncThemeFromServer(user?.preferences);
}

/** Load cached auth data from localStorage. Returns true if cache was found. */
function loadCachedAuthData(): boolean {
    try {
        const cachedUser = localStorage.getItem('cached_user');
        const cachedOrgs = localStorage.getItem('cached_orgs');
        const cachedCurrentOrg = localStorage.getItem('cached_current_org');
        if (cachedUser) {
            user = JSON.parse(cachedUser);
            orgs = cachedOrgs ? JSON.parse(cachedOrgs) : [];
            currentOrg = cachedCurrentOrg ? JSON.parse(cachedCurrentOrg) : orgs[0] ?? null;
            return true;
        }
    } catch {
        // Corrupted cache — ignore
    }
    return false;
}

/** Clear cached auth data on logout. */
function clearCachedAuthData(): void {
    localStorage.removeItem('cached_user');
    localStorage.removeItem('cached_orgs');
    localStorage.removeItem('cached_current_org');
}

/** Hydrate onboarding tour state; swallow errors (non-fatal). Lazy import avoids circular dep. */
async function hydrateTourStateSafely(): Promise<void> {
    try {
        const { hydrateTourState } = await import('$lib/onboarding/tourStore.svelte');
        await hydrateTourState();
    } catch {
        // non-fatal; tour state can remain un-hydrated
    }
}

/** Check if an error is a network failure (not a server response). */
function isNetworkError(err: unknown): boolean {
    if (err instanceof TypeError && err.message.includes('fetch')) return true;
    if (err instanceof TypeError && err.message.includes('network')) return true;
    if (err instanceof DOMException && err.name === 'AbortError') return true;
    // Check for generic "Failed to fetch" which happens when offline
    if (err instanceof TypeError && err.message === 'Failed to fetch') return true;
    return false;
}

export async function login(email: string, password: string): Promise<void> {
    const res = await authFetch<{ access_token: string }>('POST', '/auth/login', { email, password });
    token = res.access_token;
    localStorage.setItem('auth_token', token);

    // Load user profile and orgs
    user = await authFetch<User>('GET', '/auth/me');
    await loadOrgs();
    cacheAuthData();
    await hydrateTourStateSafely();
}

export async function oauthLogin(provider: 'google' | 'microsoft'): Promise<void> {
    const { generateCodeVerifier, generateCodeChallenge, generateState } = await import('$lib/oauth');

    const codeVerifier = generateCodeVerifier();
    const state = generateState();

    // Store in sessionStorage for callback
    sessionStorage.setItem(`oauth_code_verifier_${provider}`, codeVerifier);
    sessionStorage.setItem(`oauth_state_${provider}`, state);

    // Get authorization URL from backend
    const response = await fetch(`${API_BASE}/auth/oauth/${provider}/authorize`);
    if (!response.ok) {
        throw new Error(`Failed to get OAuth authorization URL`);
    }

    const { authorize_url } = await response.json() as { authorize_url: string };
    window.location.href = authorize_url;
}

export async function handleOAuthCallback(provider: string, code: string, state: string): Promise<void> {
    const codeVerifier = sessionStorage.getItem(`oauth_code_verifier_${provider}`);
    const storedState = sessionStorage.getItem(`oauth_state_${provider}`);

    if (!codeVerifier) {
        throw new Error('No PKCE verifier found in session');
    }

    if (!storedState || storedState !== state) {
        throw new Error('State token mismatch — potential CSRF attack');
    }

    // Exchange code for token
    const response = await fetch(`${API_BASE}/auth/oauth/${provider}/callback?code=${code}&state=${state}&code_verifier=${codeVerifier}`);
    if (!response.ok) {
        const error = await response.json() as { detail: string };
        throw new Error(error.detail || 'OAuth callback failed');
    }

    const { access_token } = await response.json() as { access_token: string };

    // Store token and load user
    token = access_token;
    localStorage.setItem('auth_token', token);
    user = await authFetch<User>('GET', '/auth/me');
    await loadOrgs();
    cacheAuthData();
    await hydrateTourStateSafely();

    // Clean up sessionStorage
    sessionStorage.removeItem(`oauth_code_verifier_${provider}`);
    sessionStorage.removeItem(`oauth_state_${provider}`);
}

export async function register(email: string, password: string, fullName: string): Promise<void> {
    const res = await authFetch<{ verification_token: string }>('POST', '/auth/register', {
        email,
        password,
        full_name: fullName,
    });
    token = res.verification_token;
    localStorage.setItem('auth_token', token);

    // Fetch user profile (allowed for verification scope)
    user = await authFetch<User>('GET', '/auth/me');
    // Don't load orgs or chat — verification scope blocks those endpoints
}

export async function resendVerification(): Promise<void> {
    await authFetch<{ message: string }>('POST', '/auth/resend-verification');
}

export async function handleVerificationCallback(authToken: string): Promise<void> {
    token = authToken;
    localStorage.setItem('auth_token', token);
    user = await authFetch<User>('GET', '/auth/me');
    await loadOrgs();
    cacheAuthData();
    await hydrateTourStateSafely();
}

export function logout(): void {
    token = null;
    user = null;
    currentOrg = null;
    orgs = [];
    currentOrgRoles = [];
    managedSiteIds = [];
    localStorage.removeItem('auth_token');
    clearCachedAuthData();
    // Lazy import to avoid circular dependency at module load time
    import('$lib/chat-store.svelte').then(({ resetChat }) => resetChat());
    import('$lib/project-context.svelte').then(({ clearCurrentProjectId }) =>
        clearCurrentProjectId()
    );
}

export async function switchOrg(org: Org): Promise<void> {
    try {
        const res = await authFetch<{ access_token: string }>('POST', '/auth/switch-org', {
            org_id: org.id,
        });
        token = res.access_token;
        localStorage.setItem('auth_token', token);
    } catch {
        // Fall back to client-side switch if backend call fails
    }
    currentOrg = org;
    localStorage.setItem('current_org_id', org.id);
    cacheAuthData();
    // Re-derive permission state for the newly-selected org.
    await Promise.all([refreshCurrentOrgRoles(), refreshManagedSites()]);
    import('$lib/project-context.svelte').then(({ clearCurrentProjectId }) =>
        clearCurrentProjectId()
    );
}

async function loadOrgs(): Promise<void> {
    try {
        orgs = await authFetch<Org[]>('GET', '/iam/organizations');
        // Restore previously selected org or use first
        const savedOrgId = localStorage.getItem('current_org_id');
        const saved = orgs.find((o) => o.id === savedOrgId);
        currentOrg = saved ?? orgs[0] ?? null;
    } catch {
        orgs = [];
        currentOrg = null;
    }
    // Refresh org-scoped permission state (roles + per-site grants). Both
    // are best-effort and tolerate failure.
    await Promise.all([refreshCurrentOrgRoles(), refreshManagedSites()]);
}

export async function initialize(): Promise<void> {
    if (initialized) return;

    if (!token) {
        initialized = true;
        return;
    }

    try {
        user = await authFetch<User>('GET', '/auth/me');
        if (user.email_verified) {
            await loadOrgs();
            cacheAuthData();
            await hydrateTourStateSafely();
        }
    } catch (err) {
        if (isNetworkError(err)) {
            // Network failure — load cached data instead of logging out
            const hasCached = loadCachedAuthData();
            if (!hasCached) {
                // No cache available, can't recover
                logout();
            }
        } else {
            // Server responded with error (401, etc.) — token is invalid
            logout();
        }
    } finally {
        initialized = true;
    }
}

// Test-only: allow tests to inject a user state. Not for production use.
export function __setUserForTest(value: User | null): void {
    user = value;
}
