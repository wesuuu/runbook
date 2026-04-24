import { goto } from '$app/navigation';
import { getToken, logout } from '$lib/auth.svelte';
import { API_BASE } from '$lib/config';
import { _validateResponse, type RequestOptions } from '$lib/apiValidation';
import {
    SubscriptionStateSchema,
    PortalSessionResponseSchema,
    type SubscriptionState,
    type PortalSessionResponse,
} from '$lib/schemas/billing';

export class ApiError extends Error {
    status: number;
    data: unknown;

    constructor(status: number, message: string, data: unknown = null) {
        super(message);
        this.status = status;
        this.data = data;
    }
}


function _authHeaders(contentType?: string): HeadersInit {
    const headers: HeadersInit = {};
    if (contentType) {
        headers['Content-Type'] = contentType;
    }
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
}

async function _handleErrorResponse(response: Response, fallbackMessage: string): Promise<never> {
    if (response.status === 401) {
        logout();
        goto('/login');
        throw new ApiError(401, 'Session expired');
    }

    if (response.status === 402) {
        let detail: unknown = null;
        try {
            detail = await response.json();
        } catch {
            // Body wasn't JSON
        }
        // Dynamic import to avoid circular dep on module-load order
        import('$lib/stores/lockoutModal.svelte').then(({ showLockout }) => {
            const msg =
                (detail as { detail?: { message?: string } } | null)?.detail?.message ||
                'Your subscription is not active. Add a payment method to continue.';
            showLockout(msg);
        });
        throw new ApiError(402, 'subscription_required', detail);
    }

    let errorMessage = fallbackMessage;
    let errorData = null;
    try {
        const errorJson = await response.json();
        errorMessage = errorJson.detail || errorJson.message || errorMessage;
        errorData = errorJson;
    } catch {
        // Response body not JSON
    }
    throw new ApiError(response.status, errorMessage, errorData);
}

import { normalizeEndpoint } from '$lib/normalizeEndpoint';


async function _fetchAsBlob(endpoint: string, method = 'GET', body?: unknown): Promise<Blob> {
    const headers = _authHeaders(body ? 'application/json' : undefined);
    const config: RequestInit = { method, headers };
    if (body) {
        config.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${normalizeEndpoint(endpoint)}`, config);
    if (!response.ok) {
        await _handleErrorResponse(response, 'Request failed');
    }
    return response.blob();
}

function _triggerDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function request<T>(method: string, endpoint: string, body?: unknown, options?: RequestOptions<T>): Promise<T> {
    const headers = _authHeaders('application/json');
    const config: RequestInit = { method, headers };
    if (body) {
        config.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${normalizeEndpoint(endpoint)}`, config);
    if (!response.ok) {
        await _handleErrorResponse(response, 'An error occurred');
    }

    if (response.status === 204) {
        return {} as T;
    }
    const data = await response.json();
    if (options?.schema) {
        return _validateResponse(data, options.schema, endpoint) as T;
    }
    return data;
}

async function downloadBlob(endpoint: string, filename: string): Promise<void> {
    const blob = await _fetchAsBlob(endpoint);
    _triggerDownload(blob, filename);
}

async function fetchBlobUrl(endpoint: string): Promise<string> {
    const blob = await _fetchAsBlob(endpoint);
    return URL.createObjectURL(blob);
}

async function postBlobUrl(endpoint: string, body: unknown): Promise<string> {
    const blob = await _fetchAsBlob(endpoint, 'POST', body);
    return URL.createObjectURL(blob);
}

async function postDownloadBlob(endpoint: string, body: unknown, filename: string): Promise<void> {
    const blob = await _fetchAsBlob(endpoint, 'POST', body);
    _triggerDownload(blob, filename);
}

async function uploadFile<T>(endpoint: string, file: File, fieldName = 'file'): Promise<T> {
    const form = new FormData();
    form.append(fieldName, file);
    const headers = _authHeaders();

    const response = await fetch(`${API_BASE}${normalizeEndpoint(endpoint)}`, {
        method: 'POST',
        headers,
        body: form,
    });

    if (!response.ok) {
        await _handleErrorResponse(response, 'Upload failed');
    }
    return response.json();
}

async function uploadWithFields<T>(
    endpoint: string,
    file: File,
    fields: Record<string, string>,
    fieldName = 'file',
): Promise<T> {
    const form = new FormData();
    form.append(fieldName, file);
    for (const [key, value] of Object.entries(fields)) {
        form.append(key, value);
    }
    const headers = _authHeaders(); // no Content-Type (browser sets multipart boundary)

    const response = await fetch(`${API_BASE}${normalizeEndpoint(endpoint)}`, {
        method: 'POST',
        headers,
        body: form,
    });

    if (!response.ok) {
        await _handleErrorResponse(response, 'Upload failed');
    }
    return response.json();
}

export interface SSECallbacks {
    onToolCall?: (data: { tool: string; status: string; sequence: number }) => void;
    onToolResult?: (data: { tool: string; status: string; sequence: number; summary: string }) => void;
    onComplete?: (data: { template_url: string; preview_url: string | null; variables: string[]; warnings: unknown[] }) => void;
    onError?: (data: { message: string }) => void;
}

function connectSSE(endpoint: string, callbacks: SSECallbacks): () => void {
    const token = getToken();
    const url = `${API_BASE}${normalizeEndpoint(endpoint)}${token ? `?token=${token}` : ''}`;
    const es = new EventSource(url);

    es.addEventListener('tool_call', (e: MessageEvent) => {
        callbacks.onToolCall?.(JSON.parse(e.data));
    });
    es.addEventListener('tool_result', (e: MessageEvent) => {
        callbacks.onToolResult?.(JSON.parse(e.data));
    });
    es.addEventListener('complete', (e: MessageEvent) => {
        callbacks.onComplete?.(JSON.parse(e.data));
        es.close();
    });
    es.addEventListener('error', (e: Event) => {
        if (e instanceof MessageEvent) {
            callbacks.onError?.(JSON.parse(e.data));
        } else {
            callbacks.onError?.({ message: 'Connection lost' });
        }
        es.close();
    });

    return () => es.close();
}

export const api = {
    get: <T>(endpoint: string, options?: RequestOptions<T>) => request<T>('GET', endpoint, undefined, options),
    post: <T>(endpoint: string, body?: unknown, options?: RequestOptions<T>) => request<T>('POST', endpoint, body, options),
    put: <T>(endpoint: string, body: unknown, options?: RequestOptions<T>) => request<T>('PUT', endpoint, body, options),
    patch: <T>(endpoint: string, body: unknown, options?: RequestOptions<T>) => request<T>('PATCH', endpoint, body, options),
    delete: <T>(endpoint: string, options?: RequestOptions<T>) => request<T>('DELETE', endpoint, undefined, options),
    uploadFile,
    uploadWithFields,
    downloadBlob,
    fetchBlobUrl,
    postBlobUrl,
    postDownloadBlob,
    connectSSE,
};

export const billingApi = {
    getSubscription: (): Promise<SubscriptionState> =>
        api.get<SubscriptionState>('/billing/subscription', { schema: SubscriptionStateSchema }),

    createPortalSession: (returnUrl?: string): Promise<PortalSessionResponse> =>
        api.post<PortalSessionResponse>('/billing/portal-session', { return_url: returnUrl }, { schema: PortalSessionResponseSchema }),
};
