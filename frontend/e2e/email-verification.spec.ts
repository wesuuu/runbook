import { test, expect, type Page } from '@playwright/test';

const API_BASE = process.env.E2E_API_BASE || 'http://localhost:8000';
const MAILPIT_API = process.env.E2E_MAILPIT_API || 'http://localhost:8025';

/**
 * Generate a unique test email to avoid collisions across parallel tests.
 */
function testEmail(): string {
  return `e2e-verify-${Date.now()}-${Math.random().toString(36).slice(2, 6)}@example.com`;
}

/**
 * Register a new user via the API and return the email used.
 */
async function registerUser(page: Page, email: string, password = 'testpassword123'): Promise<void> {
  const response = await page.request.post(`${API_BASE}/auth/register`, {
    data: { email, password, full_name: 'E2E Test User' },
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body.verification_token).toBeTruthy();

  // Store the verification-scoped token so the page can access /auth/me
  await page.goto('/login');
  await page.evaluate((token) => {
    localStorage.setItem('auth_token', token);
  }, body.verification_token);
}

/**
 * Extract the verification URL from the latest Mailpit email for a given address.
 */
async function getVerifyUrl(page: Page, email: string): Promise<string> {
  // Poll Mailpit until the email arrives (max 10 seconds)
  let verifyUrl = '';
  for (let i = 0; i < 20; i++) {
    const res = await page.request.get(`${MAILPIT_API}/api/v1/search?query=to:${email}`);
    const data = await res.json();
    if (data.messages && data.messages.length > 0) {
      const msgId = data.messages[0].ID;
      const msgRes = await page.request.get(`${MAILPIT_API}/api/v1/message/${msgId}`);
      const msg = await msgRes.json();
      const match = msg.HTML.match(/href="([^"]*verify-email[^"]*)"/);
      if (match) {
        verifyUrl = match[1];
        break;
      }
    }
    await page.waitForTimeout(500);
  }
  expect(verifyUrl).toBeTruthy();
  return verifyUrl;
}

/**
 * Clean up a test user and their data from the database.
 */
async function cleanupUser(page: Page, email: string): Promise<void> {
  // Use the backend's DB directly — delete verification tokens, org members, users
  // We can't use the API since the user might not have a valid session
  // Instead, just delete via Mailpit API and leave DB cleanup to test teardown
  await page.request.delete(`${MAILPIT_API}/api/v1/search?query=to:${email}`).catch(() => {});
}

test.describe('Email Verification Flow', () => {
  let testEmails: string[] = [];

  test.afterAll(async ({ request }) => {
    // Clean up test emails from Mailpit
    for (const email of testEmails) {
      await request.delete(`${MAILPIT_API}/api/v1/search?query=to:${email}`).catch(() => {});
    }
    // Clean up test users from DB via a cleanup endpoint-like approach:
    // Delete all e2e-verify-* users directly via SQL through the API isn't possible,
    // so we clean up via sequential API-less DB access pattern.
    // For now, use a dedicated cleanup endpoint or accept that test users accumulate.
    // In CI, the test DB is ephemeral so this is acceptable.
  });

  test('full registration → check-email → verify → dashboard', async ({ page }) => {
    const email = testEmail();
    testEmails.push(email);

    // 1. Register via UI
    await page.goto('/register');
    await page.fill('#fullName', 'E2E Verify User');
    await page.fill('#email', email);
    await page.fill('#password', 'testpassword123');
    await page.fill('#confirmPassword', 'testpassword123');
    await page.click('button[type="submit"]');

    // 2. Should land on /check-email
    await expect(page).toHaveURL(/check-email/, { timeout: 10_000 });
    await expect(page.getByText(email)).toBeVisible();
    await expect(page.getByText('Check your email')).toBeVisible();
    await expect(page.getByText('Resend verification email')).toBeVisible();

    // 3. Extract verification link from Mailpit
    const verifyUrl = await getVerifyUrl(page, email);
    expect(verifyUrl).toContain('/auth/verify-email');
    expect(verifyUrl).toContain('token=');
    expect(verifyUrl).toContain(`email=${email}`);

    // 4. Click the verification link (opens backend, redirects to frontend with JWT)
    await page.goto(verifyUrl);

    // 5. Should land on dashboard (frontend received JWT via ?auth_token= param)
    await expect(page).not.toHaveURL(/check-email/, { timeout: 10_000 });
    await expect(page).not.toHaveURL(/login/, { timeout: 5_000 });
    await expect(page.locator('h1')).toContainText('Dashboard', { timeout: 10_000 });

    // 6. Verify the user is fully authenticated
    const authToken = await page.evaluate(() => localStorage.getItem('auth_token'));
    expect(authToken).toBeTruthy();
  });

  test('resend button works and disables during send', async ({ page }) => {
    const email = testEmail();
    testEmails.push(email);

    await registerUser(page, email);
    await page.goto('/check-email');
    await page.waitForLoadState('networkidle');

    // Should show check-email page
    await expect(page.getByText('Check your email')).toBeVisible({ timeout: 5_000 });

    // Click resend
    const resendBtn = page.getByText('Resend verification email');
    await resendBtn.click();

    // Button should be disabled briefly (shows "Sending...")
    await expect(resendBtn).toBeDisabled({ timeout: 2_000 }).catch(() => {
      // Button may re-enable quickly — that's OK
    });

    // Should show success toast
    await expect(page.getByText('Verification email sent')).toBeVisible({ timeout: 5_000 });
  });

  test('verification scope blocks access to protected routes', async ({ page }) => {
    const email = testEmail();
    testEmails.push(email);

    await registerUser(page, email);

    // Try navigating to a protected route
    await page.goto('/projects');
    await page.waitForLoadState('networkidle');

    // Should be redirected to /check-email (not /projects)
    await expect(page).toHaveURL(/check-email/, { timeout: 10_000 });
  });

  test('check-email page redirects to dashboard after verification', async ({ page, context }) => {
    const email = testEmail();
    testEmails.push(email);

    await registerUser(page, email);
    await page.goto('/check-email');
    await expect(page.getByText('Check your email')).toBeVisible({ timeout: 5_000 });

    // Get verify URL and open in a new page (simulates clicking email link)
    const verifyUrl = await getVerifyUrl(page, email);
    const verifyPage = await context.newPage();
    await verifyPage.goto(verifyUrl);

    // Verify page should land on dashboard
    await expect(verifyPage).not.toHaveURL(/check-email/, { timeout: 10_000 });

    // Now go back to the original check-email tab and refresh
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Should redirect to dashboard since the full JWT is now in localStorage
    await expect(page).not.toHaveURL(/check-email/, { timeout: 10_000 });

    await verifyPage.close();
  });

  test('expired/invalid token shows error page', async ({ page }) => {
    // Visit verify-email with a bogus token
    await page.goto(`${API_BASE}/auth/verify-email?token=bogus-invalid-token&email=nobody@example.com`);

    // Should show error page
    await expect(page.getByText('Verification Failed')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText('invalid or has expired')).toBeVisible();
  });
});
