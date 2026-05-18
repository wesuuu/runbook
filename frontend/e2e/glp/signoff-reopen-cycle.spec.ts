import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate, loginViaApi } from '../helpers/auth';

/**
 * F-0087 Task 41b — GLP golden path: sign-off → reopen → re-sign cycle.
 *
 * Scenario:
 *   1. Run is COMPLETED.
 *   2. Study Director signs.
 *   3. QAU user signs.
 *   4. Authorized reopen user opens RunReopenModal, supplies reason,
 *      confirms. Status flips to EDITED; both prior sign-offs render as
 *      invalidated.
 *   5. Operator edits a step with edit_reason (RunEditReasonPrompt) and
 *      saves. Run transitions back to COMPLETED.
 *   6. Study Director re-signs; QAU re-signs. All rows render fresh-green.
 *
 * Currently the full chain requires a COMPLETED GLP run, which is not in
 * the seed and not yet provisionable through a single API helper. Marked
 * ``test.fixme`` with concrete unblockers below.
 */

test.use({ viewport: { width: 1280, height: 800 } });

test.describe('GLP — sign-off → reopen → re-sign cycle', () => {
    let page: Page;

    test.beforeEach(async ({ page: p }) => {
        page = p;
    });

    test.fixme(
        'study director → QAU sign, then reopen invalidates both',
        async () => {
            // BLOCKER: requires (1) a COMPLETED GLP run, (2) at least three
            // distinct users — Study Director, QAU, and an authorized
            // re-opener — all with signature_full_path set so the
            // SignoffModal will mount, and (3) seed.permissions assigning
            // "run.reopen" capability to the re-opener role. None of these
            // are in seed_db.py today.
            //
            // Promotion path:
            //   - extend seed to publish a GLP protocol and start+complete
            //     a sample run, OR
            //   - have this spec use admin API to: create run → assign
            //     roles → patch state to ACTIVE → mark all steps complete →
            //     POST /runs/{id}/complete.
            await loginAndNavigate(page, 'admin');

            // Pretend we navigated to a COMPLETED GLP run:
            const runId = '00000000-0000-0000-0000-000000000000'; // placeholder
            await page.goto(`/runs/${runId}`);

            // Switch to Study Director session (via API helper).
            // Today none of the seed users carry an explicit STUDY_DIRECTOR
            // designation; promotion needs that mapping.
            await loginViaApi(page, 'upstreamLead');
            await page
                .getByRole('button', { name: /sign as study director/i })
                .click();
            await page
                .getByLabel(/attestation/i)
                .fill('Study Director attestation.');
            await page.getByRole('button', { name: /^sign$/i }).click();
            await expect(
                page.locator('[data-role="STUDY_DIRECTOR"]'),
            ).toContainText(/signed/i);

            // Switch to QAU.
            await loginViaApi(page, 'scientist2');
            await page.reload();
            await page.getByRole('button', { name: /sign as qau/i }).click();
            await page
                .getByLabel(/attestation/i)
                .fill('QAU attestation.');
            await page.getByRole('button', { name: /^sign$/i }).click();
            await expect(page.locator('[data-role="QAU"]')).toContainText(
                /signed/i,
            );

            // Switch to an authorized re-opener and reopen.
            await loginViaApi(page, 'admin');
            await page.reload();
            await page.getByRole('button', { name: /reopen run/i }).click();
            await page
                .getByLabel(/reason/i)
                .fill('Re-evaluating data per QA finding.');
            await page
                .getByRole('button', { name: /^reopen$/i })
                .click();

            await expect(
                page.getByText(/Status:\s*EDITED/i).first(),
            ).toBeVisible();
            await expect(
                page.locator('[data-role="STUDY_DIRECTOR"]'),
            ).toHaveClass(/invalidated|strikethrough/);
            await expect(
                page.locator('[data-role="QAU"]'),
            ).toHaveClass(/invalidated|strikethrough/);
        },
    );

    test.fixme(
        'edit step with edit_reason, run completes, re-sign cycle clears',
        async () => {
            // Depends on the reopen prerequisite above. Once that fires,
            // editing a step via RunEditMode opens RunEditReasonPrompt; on
            // save the run patches to EDITED with the reasons captured, and
            // then a separate Complete-run flow returns the run to
            // COMPLETED. Study Director and QAU then sign again with the
            // expectation that both rows render fresh sign-offs (no
            // invalidated_at) and the status pill turns green.
            test.skip();
        },
    );
});
