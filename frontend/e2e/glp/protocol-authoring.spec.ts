import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate } from '../helpers/auth';
import {
    SEED,
    createProtocolViaApi,
    forceCleanupProtocol,
    updateProtocolGraph,
    buildTestGraph,
} from '../helpers/protocol';

/**
 * F-0087 Task 41b — GLP golden path: protocol authoring → approval.
 *
 * Scenarios covered:
 *  1. Open the protocol editor, toggle GLP settings, save, assert badge.
 *  2. Open the ApprovalSignatureDialog (sign as QAU) and assert sign-off row.
 *  3. Edit a graph node after sign-off; assert prior sign-off is invalidated
 *     (strikethrough / "invalidated" badge).
 *
 * Many of the assertions below depend on backend wiring that lands later in
 * the F-0087 plan (most notably: a UI control to toggle ``glpSettings.glp_enabled``
 * — currently the schema in $lib/schemas/glpSignoff lacks that field — and a
 * dedicated GLP sign-off entry point in the protocol header). Specs that
 * cannot be exercised end-to-end yet are marked ``test.fixme`` with the
 * concrete unblocker.
 */

test.use({ viewport: { width: 1280, height: 800 } });

test.describe('GLP — protocol authoring → approval', () => {
    let page: Page;
    const createdProtocolIds: string[] = [];

    test.beforeEach(async ({ page: p }) => {
        page = p;
        await loginAndNavigate(page, 'admin');
    });

    test.afterEach(async () => {
        for (const id of createdProtocolIds.splice(0)) {
            await forceCleanupProtocol(page, id);
        }
    });

    test.fixme(
        'open GLP settings panel from toolbar, toggle and apply settings',
        async () => {
            // BLOCKER: GlpSettingsPanel renders Study Director / QAU sign-off
            // requirement toggles and attestation textareas, but does NOT
            // expose a ``glp_enabled`` toggle. The plan in task 41b asks the
            // spec to "Toggle glp_enabled on" — until the UI control is added
            // (and GlpSettingsSchema extended), this branch of the spec is
            // unverifiable. Track via the F-0087 grilling addendum.
            const proto = await createProtocolViaApi(
                page,
                SEED.PROJECT_MAB_ID,
                `E2E GLP authoring ${Date.now()}`,
            );
            createdProtocolIds.push(proto.id as string);

            await page.goto(`/protocols/${proto.id}`);
            await page.waitForLoadState('networkidle');

            // Open the GLP panel via toolbar ⚖ button.
            await page
                .getByRole('button', { name: /toggle glp settings panel/i })
                .click();

            await expect(
                page.getByRole('complementary', { name: /glp settings/i }),
            ).toBeVisible();

            // (Future) Toggle glp_enabled on. Currently no such control.
            // const enableBtn = page.getByRole('button', { name: /enable glp/i });
            // await enableBtn.click();

            // Apply, save, assert the GLP-enabled badge appears.
            await page.getByRole('button', { name: /^apply$/i }).click();
            await page.getByRole('button', { name: /save protocol/i }).click();
            await expect(
                page.getByText(/glp[- ]enabled/i).first(),
            ).toBeVisible();
        },
    );

    test.fixme(
        'sign protocol as QAU via ApprovalSignatureDialog',
        async () => {
            // BLOCKER: The ApprovalSignatureDialog is gated behind the
            // standard "Submit for approval → approve" flow and requires the
            // current user to have a non-null ``signature_full_path``. The
            // seed users (admin@bioprocess.com etc.) do not have signatures
            // wired up, so the dialog renders an "upload signature" empty
            // state instead of the sign-off CTA. Unblock once the seed adds
            // signature_full_path for at least one user OR the dialog allows
            // typed attestation without a stored signature image.
            const { graph } = buildTestGraph(2);
            const proto = await createProtocolViaApi(
                page,
                SEED.PROJECT_MAB_ID,
                `E2E GLP sign QAU ${Date.now()}`,
            );
            createdProtocolIds.push(proto.id as string);
            await updateProtocolGraph(page, proto.id as string, {
                ...graph,
                glpSettings: {
                    require_study_director: false,
                    require_qau: true,
                    operator_attestation_text: '',
                    study_director_attestation_text: '',
                    qau_attestation_text: 'QAU attest',
                    step_attestation_text: '',
                },
            });

            await page.goto(`/protocols/${proto.id}`);
            await page.waitForLoadState('networkidle');

            await page
                .getByRole('button', { name: /sign as qau/i })
                .click();
            await expect(
                page.getByRole('dialog', { name: /qau sign-off/i }),
            ).toBeVisible();
            await page
                .getByLabel(/attestation/i)
                .fill('I have audited this protocol for GLP compliance.');
            await page.getByRole('button', { name: /^sign$/i }).click();

            // Sign-off row rendered, non-strikethrough.
            const row = page.locator('[data-role="QAU"]');
            await expect(row).toBeVisible();
            await expect(row).not.toHaveClass(/invalidated|strikethrough/);
        },
    );

    test.fixme(
        'editing the graph invalidates a prior QAU sign-off',
        async () => {
            // Depends on the prior test being able to actually sign a
            // protocol; same blocker (signature_full_path / QAU CTA wiring).
            // Once signing works, this spec exercises the "edit → strike"
            // invalidation path which is implemented backend-side
            // (services/signoffs/invalidate.invalidate_active_signoffs is
            // called on graph save when glp_enabled). The expected UI signal
            // is a "Strike" / "Invalidated" badge on the prior row.
            test.skip();
        },
    );
});
