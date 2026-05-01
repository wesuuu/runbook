import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E test configuration.
 *
 * Prerequisites:
 *   - Backend running on :8000 (default) with BATCHRITE_AUTH_ENABLED=true
 *     - Worktrees on alternate ports: set `E2E_API_PORT` (helpers) and
 *       `VITE_API_PORT` (frontend dev server) to the same value, e.g. `8010`.
 *   - Database seeded: cd backend && python -m app.db.seed
 *   - Frontend is auto-started by Playwright on port 5176 (avoids :5173/:5174 used by dev)
 */
const apiPort = process.env.VITE_API_PORT || process.env.E2E_API_PORT || '8000';

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
    command: `VITE_API_HOST=localhost VITE_API_PORT=${apiPort} npx vite dev --port 5176`,
    port: 5176,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
