import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate, loginViaApi } from '../helpers/auth';

/**
 * F-0087 Task 41b — GLP golden path: QAU independence enforcement.
 *
 * Scenarios:
 *  1. A user who has acted as operator on a run (signed any sign-off
 *     with role=OPERATOR, or appears in the run's role-assignments as an
 *     operator) attempts to sign as QAU and is rejected. Rejection signal
 *     may be either a toast/error or a disabled "Sign as QAU" CTA.
 *  2. A fresh QAU user with no prior involvement signs successfully.
 *
 * Backend predicate lives in services/signoffs/validators.assert_qau_independence
 * and is exercised end-to-end via POST /runs/{run_id}/signoffs returning 4xx.
 * The frontend surface today returns a generic toast on signoff failure.
 *
 * Currently blocked end-to-end (see ``test.fixme``):
 *   - Need a COMPLETED GLP run plus two seed users: one who has acted as
 *     operator on it, and a second user with no prior involvement. Today
 *     this requires API-side setup which is not yet wrapped in a helper.
 */

test.use({ viewport: { width: 1280, height: 800 } });

test.describe('GLP — QAU independence', () => {
    let page: Page;

    test.beforeEach(async ({ page: p }) => {
        page = p;
    });

    test.fixme(
        'operator-on-run cannot sign as QAU (rejection surfaced)',
        async () => {
            // BLOCKER: depends on a fixture run where a known seed user
            // (e.g. scientist1) has been recorded as an operator (role
            // assignment OR an OPERATOR signoff). Promotion path: extend
            // backend test fixtures to provision such a run and expose a
            // /test/fixtures endpoint OR have this spec walk the full flow
            // through the API before asserting on the UI.
            await loginAndNavigate(page, 'scientist1');

            const runId = '00000000-0000-0000-0000-000000000000'; // placeholder
            await page.goto(`/runs/${runId}`);
            await page.waitForLoadState('networkidle');

            const qauRow = page.locator('[data-role="QAU"]');
            const signBtn = qauRow.getByRole('button', {
                name: /sign as qau/i,
            });

            // Two acceptable rejection signals:
            //   (a) the CTA is disabled with an independence message, OR
            //   (b) clicking surfaces an error toast / dialog mentioning
            //       "independence" / "operator".
            if (await signBtn.isDisabled().catch(() => false)) {
                await expect(qauRow).toContainText(
                    /(independence|operator|cannot sign as qau)/i,
                );
            } else {
                await signBtn.click();
                await page
                    .getByLabel(/attestation/i)
                    .fill('Attempting QAU sign-off.');
                await page.getByRole('button', { name: /^sign$/i }).click();
                await expect(
                    page.getByText(/(independence|operator|cannot)/i).first(),
                ).toBeVisible({ timeout: 5_000 });
            }
        },
    );

    test.fixme(
        'fresh QAU user with no prior involvement signs successfully',
        async () => {
            // BLOCKER: same fixture run requirement as above; plus the
            // second user must have signature_full_path set so SignoffModal
            // can mount (today seed users do not).
            await loginViaApi(page, 'viewer'); // fresh, no prior involvement
            const runId = '00000000-0000-0000-0000-000000000000';
            await page.goto(`/runs/${runId}`);

            await page.getByRole('button', { name: /sign as qau/i }).click();
            await page
                .getByLabel(/attestation/i)
                .fill('QAU independent review attestation.');
            await page.getByRole('button', { name: /^sign$/i }).click();

            const qauRow = page.locator('[data-role="QAU"]');
            await expect(qauRow).toContainText(/signed/i);
            await expect(qauRow).not.toHaveClass(/invalidated|strikethrough/);
        },
    );
});
