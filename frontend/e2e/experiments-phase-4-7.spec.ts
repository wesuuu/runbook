import { test, expect } from '@playwright/test';
import { loginViaApi } from './helpers/auth';
import { experimentUrl } from './helpers/slug-urls';

/**
 * F-0043 — golden path through experiment phases 4-7.
 *
 * Walks the seeded `phases-4-7-seed` experiment (in `mAb Production v2`) with
 * three COMPLETED runs carrying key_result_value, then locks the conclusion
 * and exports the summary PDF.
 *
 * See `backend/app/db/seed.py::seed_phases_4_7_fixture` for the fixture.
 */
const EXPERIMENT_ID = '50000000-0043-0000-0000-000000000001';

test('experiment phases 4-7 golden path', async ({ page }) => {
    await loginViaApi(page, 'admin');

    const url = await experimentUrl(page, EXPERIMENT_ID);
    await page.goto(url);
    await page.waitForLoadState('networkidle');

    // Phase 4 — Awaiting conclusion lifecycle badge, conditions table, best-run dot
    await expect(page.getByText('Awaiting conclusion')).toBeVisible();
    await expect(page.locator('table.conditions-table')).toBeVisible();
    await expect(page.locator('svg circle.best')).toBeVisible();

    // Phase 5/6 — author + lock the conclusion
    await page.fill('textarea[placeholder*="conclusion"]', 'Run 3 wins by 24%.');
    await page.getByRole('button', { name: /lock conclusion/i }).first().click();

    // Phase 6 — Complete lifecycle badge + lock attestation
    await expect(page.getByText('Complete')).toBeVisible();
    await expect(page.getByText(/Locked by/)).toBeVisible();

    // Phase 7 — PDF export
    const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.getByRole('button', { name: /export summary/i }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
});
