import { billingApi, ApiError } from '$lib/api';
import type { SubscriptionState } from '$lib/schemas/billing';

let state = $state<SubscriptionState | null>(null);
let loading = $state(false);
let error = $state<string | null>(null);
let unconfigured = $state(false);

export const subscription = {
    get state() { return state; },
    get loading() { return loading; },
    get error() { return error; },
    get unconfigured() { return unconfigured; },
};

export async function loadSubscription(): Promise<void> {
    loading = true;
    error = null;
    unconfigured = false;
    try {
        state = await billingApi.getSubscription();
    } catch (e) {
        if (e instanceof ApiError && e.status === 503) {
            unconfigured = true;
            state = null;
        } else if (e instanceof ApiError && e.status === 403) {
            state = null;
        } else {
            error = e instanceof Error ? e.message : 'Failed to load subscription';
        }
    } finally {
        loading = false;
    }
}

export async function openPortal(returnUrl?: string): Promise<void> {
    const resolvedReturn = returnUrl ?? `${window.location.origin}/settings?tab=billing`;
    try {
        const { url } = await billingApi.createPortalSession(resolvedReturn);
        window.location.href = url;
    } catch (e) {
        error = e instanceof Error ? e.message : 'Failed to open billing portal';
    }
}
