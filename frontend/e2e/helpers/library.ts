import { type Page } from '@playwright/test';
import { API_BASE } from './apiBase';

/**
 * Make an authenticated API request using the token from localStorage.
 */
async function apiRequest(
    page: Page,
    method: string,
    path: string,
    body?: unknown,
): Promise<unknown> {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const headers: Record<string, string> = {
        Authorization: `Bearer ${token}`,
    };
    const options: Parameters<Page['request']['fetch']>[1] = {
        method,
        headers,
    };
    if (body && method !== 'GET') {
        headers['Content-Type'] = 'application/json';
        options.data = body;
    }
    const response = await page.request.fetch(`${API_BASE}${path}`, options);
    if (!response.ok()) {
        throw new Error(`API ${method} ${path} failed: ${response.status()}`);
    }
    if (response.status() === 204) return {};
    return response.json();
}

/**
 * Upload a text document via the API for testing.
 */
export async function uploadDocumentViaApi(
    page: Page,
    title: string,
    content = 'This is test document content for E2E testing.',
): Promise<{ id: string; title: string; status: string }> {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const boundary = '----E2ETestBoundary';
    const body = [
        `--${boundary}`,
        'Content-Disposition: form-data; name="file"; filename="test.txt"',
        'Content-Type: text/plain',
        '',
        content,
        `--${boundary}`,
        `Content-Disposition: form-data; name="title"`,
        '',
        title,
        `--${boundary}--`,
    ].join('\r\n');

    const response = await page.request.fetch(`${API_BASE}/library/documents`, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': `multipart/form-data; boundary=${boundary}`,
        },
        data: Buffer.from(body),
    });

    if (!response.ok()) {
        throw new Error(`Upload failed: ${response.status()}`);
    }
    return response.json();
}

/**
 * Get a document by ID via the API.
 */
export async function getDocumentViaApi(
    page: Page,
    id: string,
): Promise<unknown> {
    return apiRequest(page, 'GET', `/library/documents/${id}`);
}

/**
 * Delete a document by ID via the API.
 */
export async function deleteDocumentViaApi(
    page: Page,
    id: string,
): Promise<void> {
    await apiRequest(page, 'DELETE', `/library/documents/${id}`);
}

/**
 * Upload a binary file (PDF, DOCX, image) via the API for testing.
 */
export async function uploadBinaryDocumentViaApi(
    page: Page,
    title: string,
    filePath: string,
    fileName: string,
    mimeType: string,
): Promise<{ id: string; title: string; status: string }> {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const fs = await import('fs');
    const fileBuffer = fs.readFileSync(filePath);

    const response = await page.request.fetch(`${API_BASE}/library/documents`, {
        method: 'POST',
        multipart: {
            file: {
                name: fileName,
                mimeType: mimeType,
                buffer: fileBuffer,
            },
            title: title,
        },
        headers: {
            Authorization: `Bearer ${token}`,
        },
    });

    if (!response.ok()) {
        throw new Error(`Upload failed: ${response.status()}`);
    }
    return response.json();
}

/**
 * Wait for a document to reach INDEXED status by polling.
 */
export async function waitForIndexed(
    page: Page,
    docId: string,
    timeoutMs = 30000,
): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        const doc = (await getDocumentViaApi(page, docId)) as {
            status: string;
        };
        if (doc.status === 'INDEXED') return;
        if (doc.status === 'FAILED')
            throw new Error('Document processing failed');
        await page.waitForTimeout(1000);
    }
    throw new Error(`Document did not reach INDEXED within ${timeoutMs}ms`);
}
