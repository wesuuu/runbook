import { Page } from '@playwright/test';

/**
 * Login via API and inject token into localStorage.
 * Avoids UI form testing, focuses on feature testing.
 */
export async function loginViaApi(page: Page, email: string, password: string = 'password'): Promise<string> {
    const response = await page.request.post('http://localhost:8000/auth/login', {
        data: { email, password },
    });

    if (!response.ok()) {
        throw new Error(`Login failed: ${response.status()} ${response.statusText()}`);
    }

    const data = await response.json() as { access_token?: string };
    const token = data.access_token;

    if (!token) {
        throw new Error('No access_token in login response');
    }

    // Inject token via script on a public page
    await page.goto('/');
    await page.evaluate((t) => {
        localStorage.setItem('auth_token', t);
    }, token);

    // Hard refresh to pick up new token
    await page.reload();

    return token;
}

/**
 * Check if backend has auth enabled.
 */
export async function isAuthEnabled(page: Page): Promise<boolean> {
    // Try to access a protected endpoint without auth
    const response = await page.request.get('http://localhost:8000/auth/me');
    // If 401, auth is enabled. If 200, it's disabled.
    return response.status() === 401;
}
