import { goto } from '$app/navigation';
import { getToken, logout } from '$lib/auth.svelte';

const API_BASE = 'http://localhost:8000';

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

export const api = {
    get: <T>(endpoint: string) => request<T>('GET', endpoint),
    post: <T>(endpoint: string, body: unknown) => request<T>('POST', endpoint, body),
    put: <T>(endpoint: string, body: unknown) => request<T>('PUT', endpoint, body),
    delete: <T>(endpoint: string) => request<T>('DELETE', endpoint),
};
