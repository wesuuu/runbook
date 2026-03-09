import { test, expect } from '@playwright/test';
import { TEST_USERS, loginAndNavigate, isAuthEnabled } from './helpers/auth';

test.describe('Authentication', () => {

  test.beforeEach(async ({ page }) => {
    // Start each test with a clean slate — clear any leftover auth state
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('current_org_id');
    });
  });

  // --- Test 1: Successful login ---
  test('successful login redirects to dashboard and shows user info', async ({ page }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');

    await page.fill('#email', TEST_USERS.admin.email);
    await page.fill('#password', TEST_USERS.admin.password);
    await page.click('button[type="submit"]');

    // Should redirect away from login to dashboard
    await expect(page).not.toHaveURL(/.*login/, { timeout: 15_000 });

    // The dashboard greeting includes the user's first name: "Admin's Dashboard"
    await expect(page.locator('h1')).toContainText('Dashboard', { timeout: 10_000 });
  });

  // --- Test 2: Failed login with wrong password ---
  // Requires backend with RUNBOOK_AUTH_ENABLED=true (the default).
  // Skips automatically when auth is disabled (dev mode).
  test('wrong password shows error and stays on login page', async ({ page }) => {
    const authOn = await isAuthEnabled(page);
    test.skip(!authOn, 'Backend has auth_enabled=false — login rejection cannot be tested');

    await page.goto('/login');

    await page.fill('#email', TEST_USERS.admin.email);
    await page.fill('#password', 'wrongpassword');
    await page.click('button[type="submit"]');

    // Should stay on login page
    await expect(page).toHaveURL(/.*login/);

    // Error message should be visible
    await expect(page.locator('[class*="destructive"]')).toBeVisible();
  });

  // --- Test 3: Failed login with non-existent email ---
  // Requires backend with RUNBOOK_AUTH_ENABLED=true (the default).
  // Skips automatically when auth is disabled (dev mode).
  test('non-existent email shows error and stays on login page', async ({ page }) => {
    const authOn = await isAuthEnabled(page);
    test.skip(!authOn, 'Backend has auth_enabled=false — login rejection cannot be tested');

    await page.goto('/login');

    await page.fill('#email', 'nobody@doesnotexist.com');
    await page.fill('#password', 'anypassword');
    await page.click('button[type="submit"]');

    // Should stay on login page
    await expect(page).toHaveURL(/.*login/);

    // Error message should be visible
    await expect(page.locator('[class*="destructive"]')).toBeVisible();
  });

  // --- Test 4: Route protection ---
  test('unauthenticated user is redirected to /login', async ({ page }) => {
    await page.evaluate(() => localStorage.removeItem('auth_token'));

    await page.goto('/projects');
    await page.waitForURL('**/login');

    await expect(page).toHaveURL(/.*login/);
  });

  // --- Test 5: Session persistence across reload ---
  test('session persists after page reload', async ({ page }) => {
    await loginAndNavigate(page, 'admin');

    // Verify we're on the dashboard (not redirected to login)
    await expect(page).not.toHaveURL(/.*login/, { timeout: 10_000 });
    await expect(page.locator('h1')).toContainText('Dashboard', { timeout: 10_000 });

    // Reload the page
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Should still be on dashboard, not redirected to login
    await expect(page).not.toHaveURL(/.*login/, { timeout: 10_000 });
    await expect(page.locator('h1')).toContainText('Dashboard', { timeout: 10_000 });
  });

  // --- Test 6: Logout ---
  test('logout clears session and redirects to login', async ({ page }) => {
    await loginAndNavigate(page, 'admin');
    await expect(page).not.toHaveURL(/.*login/, { timeout: 10_000 });

    // Open user menu — the last dropdown trigger in the navbar (user avatar/initials)
    await page.locator('[data-slot="dropdown-menu-trigger"]').last().click();

    // Click Sign Out
    await page.getByText('Sign Out').click();

    // Should redirect to login
    await page.waitForURL('**/login', { timeout: 10_000 });
    await expect(page).toHaveURL(/.*login/);

    // Token should be cleared from localStorage
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeNull();

    // Protected routes should redirect back to login
    await page.goto('/projects');
    await page.waitForURL('**/login');
    await expect(page).toHaveURL(/.*login/);
  });

  // --- Test 7: Invalid/expired token triggers auto-logout ---
  test('invalid token in localStorage triggers auto-logout', async ({ page }) => {
    // Set a garbage token on the login page (public route)
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'invalid-garbage-token');
    });

    // Navigate to a protected page — the app should try /auth/me, get 401, and logout
    await page.goto('/');
    await page.waitForURL('**/login', { timeout: 10_000 });

    await expect(page).toHaveURL(/.*login/);

    // Token should have been cleared
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(token).toBeNull();
  });

  // --- Test 8: Organization switching ---
  test('switching organization reloads with new context', async ({ page }) => {
    await loginAndNavigate(page, 'admin');
    await expect(page).not.toHaveURL(/.*login/, { timeout: 10_000 });

    // Store the initial org ID
    const initialOrgId = await page.evaluate(() => localStorage.getItem('current_org_id'));

    // Open user menu — the last dropdown trigger in the navbar (user avatar/initials)
    await page.locator('[data-slot="dropdown-menu-trigger"]').last().click();

    // Verify we can see both org names in the menu
    const menuContent = page.locator('[data-slot="dropdown-menu-content"]');
    await expect(menuContent).toBeVisible();
    await expect(menuContent).toContainText('BioProcess Inc');
    await expect(menuContent).toContainText('Acme Biologics');

    // Click the other org
    await menuContent.getByText('Acme Biologics').click();

    // Org switching triggers a full page reload
    await page.waitForLoadState('networkidle');

    // The current_org_id in localStorage should have changed
    const newOrgId = await page.evaluate(() => localStorage.getItem('current_org_id'));
    expect(newOrgId).toBeTruthy();
    expect(newOrgId).not.toEqual(initialOrgId);
  });
});
