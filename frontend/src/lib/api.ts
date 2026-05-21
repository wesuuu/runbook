import { goto } from '$app/navigation';
import { streamSse, type SseEvent } from '$lib/ai/sse-stream';
import { getToken, logout } from '$lib/auth.svelte';
import { API_BASE } from '$lib/config';
import { _validateResponse, type RequestOptions } from '$lib/apiValidation';
import {
    SubscriptionStateSchema,
    PortalSessionResponseSchema,
    type SubscriptionState,
    type PortalSessionResponse,
} from '$lib/schemas/billing';
import type { ApprovalRequest } from '$lib/schemas/chat';
import { ProtocolSchema, type Protocol } from '$lib/schemas/protocols';
import {
    GlpSignoffResponseSchema,
    GlpSignoffResponseListSchema,
    AwaitingApprovalListSchema,
    type GlpSignoffCreate,
    type GlpSignoffResponse,
    type GlpSignoffResponseList,
    type AwaitingApprovalList,
    type ApproveProtocolRequest,
    type RejectProtocolRequest,
} from '$lib/schemas/glpSignoff';
import { SignoffRequestListSchema, type SignoffRequestList } from '$lib/schemas/signoffRequests';

import { ApiError, extractErrorMessage } from '$lib/apiError';

export { ApiError } from '$lib/apiError';


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
        // Backend `detail` may be a string, a structured object, or a 422
        // validation array — extractErrorMessage normalises all three so the
        // ApiError.message is always real text, never "[object Object]".
        errorMessage = extractErrorMessage(errorJson, fallbackMessage);
        errorData = errorJson;
    } catch {
        // Response body not JSON
    }
    throw new ApiError(response.status, errorMessage, errorData);
}

import { normalizeEndpoint } from '$lib/normalizeEndpoint';
import { toast } from '$lib/toast';


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
    const unresolved = response.headers.get('X-Unresolved-Placeholders');
    if (unresolved) {
        toast.warning(
            'Unresolved template variables',
            `${unresolved}. They remain literal in the document.`,
        );
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

// --- Protocol Approval (F-0066) ---

export function designateProtocolApproval(
    protocolId: string,
    requiresApproval: boolean,
): Promise<Protocol> {
    return api.post<Protocol>(
        `/protocols/${protocolId}/designate-approval`,
        { requires_approval: requiresApproval },
        { schema: ProtocolSchema },
    );
}

export function submitProtocolForApproval(
    protocolId: string,
    requestedUserIds: string[],
): Promise<Protocol> {
    return api.post<Protocol>(
        `/protocols/${protocolId}/submit-for-approval`,
        { requested_user_ids: requestedUserIds },
        { schema: ProtocolSchema },
    );
}

export function approveProtocol(
    protocolId: string,
    body: ApproveProtocolRequest = {},
): Promise<Protocol> {
    return api.post<Protocol>(
        `/protocols/${protocolId}/approve`,
        body,
        { schema: ProtocolSchema },
    );
}

export function rejectProtocol(
    protocolId: string,
    body: RejectProtocolRequest,
): Promise<Protocol> {
    return api.post<Protocol>(
        `/protocols/${protocolId}/reject`,
        body,
        { schema: ProtocolSchema },
    );
}

export function getProtocolSignoffs(
    protocolId: string,
): Promise<GlpSignoffResponseList> {
    return api.get<GlpSignoffResponseList>(
        `/protocols/${protocolId}/signoffs`,
        { schema: GlpSignoffResponseListSchema },
    );
}

export function getAwaitingMyApproval(): Promise<AwaitingApprovalList> {
    return api.get<AwaitingApprovalList>(
        '/protocols/awaiting-my-approval',
        { schema: AwaitingApprovalListSchema },
    );
}

export function listRunSignoffs(
    runId: string,
    activeOnly = false,
): Promise<GlpSignoffResponseList> {
    return api.get<GlpSignoffResponseList>(
        `/runs/${runId}/signoffs?active=${activeOnly}`,
        { schema: GlpSignoffResponseListSchema },
    );
}

export function createRunSignoff(
    runId: string,
    payload: GlpSignoffCreate,
): Promise<GlpSignoffResponse> {
    return api.post<GlpSignoffResponse>(
        `/runs/${runId}/signoffs`,
        payload,
        { schema: GlpSignoffResponseSchema },
    );
}

export function listProtocolSignoffs(
    protocolId: string,
    activeOnly = false,
): Promise<GlpSignoffResponseList> {
    return api.get<GlpSignoffResponseList>(
        `/protocols/${protocolId}/signoffs?active=${activeOnly}`,
        { schema: GlpSignoffResponseListSchema },
    );
}

export function createProtocolSignoff(
    protocolId: string,
    payload: GlpSignoffCreate,
): Promise<GlpSignoffResponse> {
    return api.post<GlpSignoffResponse>(
        `/protocols/${protocolId}/signoffs`,
        payload,
        { schema: GlpSignoffResponseSchema },
    );
}

export function completeRun(
    runId: string,
    outcome: string,
    outcomeNotes?: string,
): Promise<unknown> {
    return api.post<unknown>(`/runs/${runId}/complete`, {
        outcome,
        outcome_notes: outcomeNotes,
    });
}

export function reopenRun(runId: string, reason: string): Promise<unknown> {
    return api.post<unknown>(`/runs/${runId}/reopen`, { reason });
}

// --- Sign-off review queue (F-0080) ---

export function listSignoffRequests(): Promise<SignoffRequestList> {
    return api.get<SignoffRequestList>('/signoff-requests', {
        schema: SignoffRequestListSchema,
    });
}

export function updateRunReviewers(
    runId: string,
    reviewers: { study_director_id: string | null; qau_reviewer_id: string | null },
): Promise<unknown> {
    return api.put<unknown>(`/runs/${runId}/reviewers`, reviewers);
}

export const glpSignoffApi = {
    designate: designateProtocolApproval,
    submit: submitProtocolForApproval,
    approve: approveProtocol,
    reject: rejectProtocol,
    signoffs: getProtocolSignoffs,
    awaitingMine: getAwaitingMyApproval,
    listRunSignoffs,
    createRunSignoff,
    listProtocolSignoffs,
    createProtocolSignoff,
    completeRun,
    reopenRun,
};

export const billingApi = {
    getSubscription: (): Promise<SubscriptionState> =>
        api.get<SubscriptionState>('/billing/subscription', { schema: SubscriptionStateSchema }),

    createPortalSession: (returnUrl?: string): Promise<PortalSessionResponse> =>
        api.post<PortalSessionResponse>('/billing/portal-session', { return_url: returnUrl }, { schema: PortalSessionResponseSchema }),
};

// --- External-protocol approval (F-0084) ---

/**
 * Approve or reject a pending external-protocol conversion. The response is
 * an SSE stream of the resumed turn — pass `onEvent` to react to events
 * (tool_start/tool_end/done/error).
 */
export async function streamApprovalDecision(
    sessionId: string,
    body: ApprovalRequest,
    onEvent: (event: SseEvent) => void,
): Promise<void> {
    return streamSse(`/chat/sessions/${sessionId}/messages/approve`, body, onEvent);
}
