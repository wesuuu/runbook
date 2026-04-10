import { type Page } from '@playwright/test';

const API_BASE = 'http://localhost:8000';

/** Seed user credentials from backend/app/db/seed.py */
export const TEST_USERS = {
  admin: { email: 'admin@bioprocess.com', password: 'password123', name: 'Admin User' },
  upstreamLead: { email: 'upstream.lead@bioprocess.com', password: 'password123', name: 'Upstream Lead' },
  downstreamLead: { email: 'downstream.lead@bioprocess.com', password: 'password123', name: 'Downstream Lead' },
  scientist1: { email: 'scientist1@bioprocess.com', password: 'password123', name: 'Scientist One' },
  scientist2: { email: 'scientist2@bioprocess.com', password: 'password123', name: 'Scientist Two' },
  viewer: { email: 'viewer@bioprocess.com', password: 'password123', name: 'Viewer User' },
} as const;

export type TestUserKey = keyof typeof TEST_USERS;

/**
 * Login via the API and inject the token into the page's localStorage.
 * Sets the token on the /login page (public route) so no redirect interferes.
 */
export async function loginViaApi(page: Page, userKey: TestUserKey): Promise<string> {
  const { email, password } = TEST_USERS[userKey];

  const response = await page.request.post(`${API_BASE}/auth/login`, {
    data: { email, password },
  });

  if (!response.ok()) {
    throw new Error(`Login API failed for ${email}: ${response.status()}`);
  }

  const { access_token } = await response.json();

  // Set token on a public page so the route guard doesn't interfere
  await page.goto('/login');
  await page.evaluate((token) => {
    localStorage.setItem('auth_token', token);
  }, access_token);

  return access_token;
}

/**
 * Login via the API, set token in localStorage, then navigate to the target path.
 * The app's initialize() will pick up the token and load user/orgs.
 */
export async function loginAndNavigate(page: Page, userKey: TestUserKey, path = '/'): Promise<void> {
  await loginViaApi(page, userKey);
  await page.goto(path);
  await page.waitForLoadState('networkidle');
}

/**
 * Check if the backend has auth_enabled=true by attempting a bad login.
 * Returns true if auth is enforced (bad login is rejected).
 */
export async function isAuthEnabled(page: Page): Promise<boolean> {
  const response = await page.request.post(`${API_BASE}/auth/login`, {
    data: { email: 'e2e-probe@nonexistent.test', password: 'probe' },
  });
  // If auth is disabled, the backend returns 200 for any credentials
  return !response.ok();
}
