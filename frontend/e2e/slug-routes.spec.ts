import { test, expect } from '@playwright/test';
import { loginViaApi } from './helpers/auth';
import { SEED, createRunViaApi, cleanupE2eExperiments } from './helpers/experiment';
import {
  createProtocolViaApi,
  updateProtocolGraph,
  buildTestGraph,
  forceCleanupProtocol,
} from './helpers/protocol';
import { projectsUrl, runUrl } from './helpers/slug-urls';

/**
 * F-0091: GitHub-style frontend routes — /[org]/[object]/[slug].
 *
 * Verifies the slug-based URL structure end-to-end: the projects list lives
 * under the org segment, drilling into a project produces a slug URL, runs
 * are addressable nested under their project, and an unknown org slug 404s.
 *
 * The base seed (`app.db.seed`) creates projects but no protocols or runs,
 * so the run test provisions its own protocol + run via the API.
 */
test.use({ viewport: { width: 1280, height: 720 } });

test.describe('F-0091 — slug-based browser routes', () => {
  test('navigates projects list -> project detail through slug URLs', async ({ page }) => {
    await loginViaApi(page, 'admin');

    // The projects list lives at /[org]/projects.
    await page.goto(await projectsUrl(page));
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveURL(/\/[a-z0-9-]+\/projects$/);

    // Clicking a project drills into /[org]/projects/[projectSlug].
    await page.getByRole('link', { name: /mAb Production v2/i }).first().click();
    await expect(page).toHaveURL(/\/[a-z0-9-]+\/projects\/[a-z0-9-]+$/);
  });

  test('a run is addressable at /[org]/projects/[projectSlug]/runs/[slug]', async ({ page }) => {
    await loginViaApi(page, 'admin');

    // Seed has no protocols/runs — provision a runnable protocol first.
    const stamp = Date.now();
    const protocol = await createProtocolViaApi(
      page,
      SEED.PROJECT_MAB_ID,
      `E2E SlugRoute Protocol ${stamp}`,
    );
    const protocolId = protocol.id as string;
    try {
      await updateProtocolGraph(page, protocolId, buildTestGraph(2).graph);

      const runName = `E2E SlugRoute Run ${stamp}`;
      const runId = await createRunViaApi(
        page,
        runName,
        SEED.PROJECT_MAB_ID,
        protocolId,
      );

      // runUrl resolves the run + project slugs and assembles the nested path.
      await page.goto(await runUrl(page, runId));
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveURL(
        /\/[a-z0-9-]+\/projects\/[a-z0-9-]+\/runs\/[a-z0-9-]+$/,
      );
      // The run detail page rendered — not the 404 fallback.
      await expect(page.getByText(runName)).toBeVisible({ timeout: 10_000 });
    } finally {
      await cleanupE2eExperiments(page, SEED.PROJECT_MAB_ID);
      await forceCleanupProtocol(page, protocolId);
    }
  });

  test('an unknown org slug renders the 404 page', async ({ page }) => {
    await loginViaApi(page, 'admin');

    await page.goto('/no-such-org/protocols/anything');
    await expect(page.getByText('404')).toBeVisible();
    await expect(page.getByText(/organization not found/i)).toBeVisible();
  });
});
