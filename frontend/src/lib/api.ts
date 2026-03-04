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

async function request<T>(method: string, endpoint: string, body?: unknown): Promise<T> {
    const headers: HeadersInit = {
        'Content-Type': 'application/json',
    };

    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const config: RequestInit = {
        method,
        headers,
    };

    if (body) {
        config.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${endpoint}`, config);
    console.log(API_BASE + endpoint, config);

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            goto('/login');
            throw new ApiError(401, 'Session expired');
        }

        let errorMessage = 'An error occurred';
        let errorData = null;
        try {
            const errorJson = await response.json();
            errorMessage = errorJson.detail || errorJson.message || errorMessage;
            errorData = errorJson;
        } catch {
            // ignore
        }
        throw new ApiError(response.status, errorMessage, errorData);
    }

    // Handle 204 No Content
    if (response.status === 204) {
        return {} as T;
    }

    return response.json();
}

async function downloadBlob(endpoint: string, filename: string): Promise<void> {
    const headers: HeadersInit = {};
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, { headers });

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            goto('/login');
            throw new ApiError(401, 'Session expired');
        }
        throw new ApiError(response.status, 'Download failed');
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function fetchBlobUrl(endpoint: string): Promise<string> {
    const headers: HeadersInit = {};
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, { headers });

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            goto('/login');
            throw new ApiError(401, 'Session expired');
        }
        throw new ApiError(response.status, 'Failed to fetch PDF');
    }

    const blob = await response.blob();
    return URL.createObjectURL(blob);
}

async function postBlobUrl(endpoint: string, body: unknown): Promise<string> {
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            goto('/login');
            throw new ApiError(401, 'Session expired');
        }
        throw new ApiError(response.status, 'Failed to fetch PDF');
    }

    const blob = await response.blob();
    return URL.createObjectURL(blob);
}

async function postDownloadBlob(endpoint: string, body: unknown, filename: string): Promise<void> {
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            goto('/login');
            throw new ApiError(401, 'Session expired');
        }
        throw new ApiError(response.status, 'Download failed');
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

export const api = {
    get: <T>(endpoint: string) => request<T>('GET', endpoint),
    post: <T>(endpoint: string, body: unknown) => request<T>('POST', endpoint, body),
    put: <T>(endpoint: string, body: unknown) => request<T>('PUT', endpoint, body),
    delete: <T>(endpoint: string) => request<T>('DELETE', endpoint),
    downloadBlob,
    fetchBlobUrl,
    postBlobUrl,
    postDownloadBlob,
};
