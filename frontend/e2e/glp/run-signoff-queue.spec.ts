import { test, expect } from '@playwright/test';
import { loginAndNavigate } from '../helpers/auth';

test.describe('Run sign-off review queue (F-0080)', () => {
    test('reviews page is reachable from the nav', async ({ page }) => {
        await loginAndNavigate(page, 'admin', '/');
        await page.locator('nav a:has-text("Reviews")').first().click();
        // waitForURL (not waitForLoadState) — the nav is a SvelteKit
        // client-side transition with no network round-trip, so 'networkidle'
        // resolves before the URL updates.
        await page.waitForURL('**/reviews');
        expect(page.url()).toContain('/reviews');
        await expect(page.getByText('Awaiting your review')).toBeVisible();
    });

    test('queue shows an empty state when nothing is pending', async ({ page }) => {
        await loginAndNavigate(page, 'viewer', '/reviews');
        await expect(page.getByText(/all caught up/i)).toBeVisible();
    });
});
