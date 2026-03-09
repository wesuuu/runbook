import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E test configuration.
 *
 * Prerequisites:
 *   - Backend running on :8000 with RUNBOOK_AUTH_ENABLED=true (the default)
 *   - Database seeded: cd backend && python -m app.db.seed
 *   - Frontend is auto-started by Playwright on port 5176 (avoids :5173/:5174 used by dev)
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',

  use: {
    baseURL: 'http://localhost:5176',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'VITE_API_HOST=localhost npx vite dev --port 5176',
    port: 5176,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
