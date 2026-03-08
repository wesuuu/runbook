import { goto } from '$app/navigation';
import { getToken, logout } from '$lib/auth.svelte';
import { API_BASE } from '$lib/config';

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

async function _fetchAsBlob(endpoint: string, method = 'GET', body?: unknown): Promise<Blob> {
    const headers = _authHeaders(body ? 'application/json' : undefined);
    const config: RequestInit = { method, headers };
    if (body) {
        config.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${endpoint}`, config);
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

async function request<T>(method: string, endpoint: string, body?: unknown): Promise<T> {
    const headers = _authHeaders('application/json');
    const config: RequestInit = { method, headers };
    if (body) {
        config.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${endpoint}`, config);
    if (!response.ok) {
        await _handleErrorResponse(response, 'An error occurred');
    }

    if (response.status === 204) {
        return {} as T;
    }
    return response.json();
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

    const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers,
        body: form,
    });

    if (!response.ok) {
        await _handleErrorResponse(response, 'Upload failed');
    }
    return response.json();
}

export const api = {
    get: <T>(endpoint: string) => request<T>('GET', endpoint),
    post: <T>(endpoint: string, body: unknown) => request<T>('POST', endpoint, body),
    put: <T>(endpoint: string, body: unknown) => request<T>('PUT', endpoint, body),
    delete: <T>(endpoint: string) => request<T>('DELETE', endpoint),
    uploadFile,
    downloadBlob,
    fetchBlobUrl,
    postBlobUrl,
    postDownloadBlob,
};
