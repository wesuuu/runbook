import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate } from '../helpers/auth';
import { SEED } from '../helpers/protocol';
import { projectUrl } from '../helpers/slug-urls';

/**
 * F-0087 Task 41b — GLP golden path: run execution → completion.
 *
 * Scenarios:
 *   1. Operator creates a run from a GLP-enabled protocol.
 *   2. Roles get assigned, run is started.
 *   3. If linked equipment is expired, the ``ConfirmDialog`` mounts with
 *      "out of compliance" wording — operator confirms.
 *   4. Step executed (actual value entered). Run completes with outcome
 *      ``COMPLETED_NORMAL``.
 *   5. Status COMPLETED and outcome visible.
 *
 * Currently blocked end-to-end (see ``test.fixme`` reasons below):
 *   - The seed does not include a GLP-enabled published protocol.
 *   - The equipment-out-of-compliance ConfirmDialog is not wired through
 *     the Start flow yet (F-0087 task 41a tracks the related xfail).
 *
 * Specs are structured so they can be promoted to ``test()`` once those gaps
 * close, without rewriting the harness scaffolding.
 */

test.use({ viewport: { width: 1280, height: 800 } });

test.describe('GLP — run execution → completion', () => {
    let page: Page;

    test.beforeEach(async ({ page: p }) => {
        page = p;
        await loginAndNavigate(page, 'scientist1');
    });

    test.fixme(
        'create run from GLP-enabled protocol, assign roles, start',
        async () => {
            // BLOCKER: seed_db.py does not currently create a GLP-enabled
            // published protocol (graph.glpSettings.glp_enabled=true with
            // version_number > 0). Until the seed adds one (or until this
            // spec self-provisions one through admin login + API), the run
            // creator has no GLP protocol to target.
            //
            // Self-provision path (when promoting this spec):
            //   1. log in as admin via API
            //   2. POST /protocols  (org-scoped)
            //   3. PUT  /protocols/{id} with the glpProtocolGraph
            //      fixture under graph.glpSettings.glp_enabled=true
            //   4. POST /protocols/{id}/publish-version
            //   5. switch session to scientist1 for the operator flow
            await page.goto(await projectUrl(page, SEED.PROJECT_MAB_ID));
            await page.getByRole('button', { name: /\+ New Run/i }).click();
            await expect(
                page.getByRole('heading', { name: /New Run/i }),
            ).toBeVisible();

            // Step 1 — name
            await page
                .getByLabel(/Name/i)
                .fill(`E2E GLP run ${Date.now()}`);
            await page.getByRole('button', { name: /^Continue/ }).click();

            // Step 2 — select the GLP protocol (here by partial name match)
            await page
                .getByLabel(/Protocol/i)
                .selectOption({ label: /GLP/i });
            await page.getByRole('button', { name: /^Continue/ }).click();

            // Step 3 — overrides (leave defaults)
            await page
                .getByRole('button', { name: /Continue to review/i })
                .click();

            // Step 4 — review & create
            await page.getByRole('button', { name: /Create run/i }).click();

            await expect(page).toHaveURL(/\/projects\/[a-z0-9-]+\/runs\/[a-z0-9-]+$/);

            // Role assignment + start (RoleAssignmentPanel)
            await page.getByRole('button', { name: /assign me/i }).click();
            await page.getByRole('button', { name: /^start( run)?$/i }).click();
            await expect(
                page.getByText(/Status:\s*ACTIVE/i).first(),
            ).toBeVisible();
        },
    );

    test.fixme(
        'expired equipment surfaces out-of-compliance ConfirmDialog on start',
        async () => {
            // BLOCKER: F-0087 Task 41a backend xfails confirm the
            // expired-equipment gate at the model + service layer, but the
            // ConfirmDialog wiring into the Start flow is not yet shipped in
            // the run page. When implemented, the dialog should:
            //   - mount synchronously on Start click,
            //   - render copy containing "out of compliance",
            //   - allow Confirm to proceed and Cancel to abort.
            test.skip();
        },
    );

    test.fixme(
        'execute step, complete run with COMPLETED_NORMAL outcome',
        async () => {
            // BLOCKER: Depends on the create-run / start-run spec above. Once
            // a GLP run is ACTIVE, the operator should be able to:
            //   - enter an actual value on the first step,
            //   - click "Complete run",
            //   - choose outcome COMPLETED_NORMAL (RunOutcomePicker),
            //   - submit; status badge transitions to COMPLETED and outcome
            //     pill renders the chosen value.
            test.skip();
        },
    );
});
