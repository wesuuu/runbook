import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate } from './helpers/auth';
import { SEED } from './helpers/protocol';
import {
    buildGraph,
    seedScenarioProtocol,
    seedExperimentForFixture,
    cleanupAllFixtures,
    FIXTURE_PREFIX,
    type RoleSpec,
} from './helpers/runOverridesFixtures';
import { projectUrl, experimentUrl } from './helpers/slug-urls';

test.use({ viewport: { width: 1280, height: 800 } });
test.describe.configure({ mode: 'serial' });

const PROJECT_ID = SEED.PROJECT_MAB_ID;

test.describe('F-0081 Run Creator — scenario matrix', () => {
    let page: Page;

    test.beforeAll(async ({ browser }) => {
        page = await browser.newPage();
        await loginAndNavigate(page, 'admin');
        // eslint-disable-next-line no-console
        console.log(`[F-0081] Fixture prefix this run: "${FIXTURE_PREFIX}"`);
    });

    test.afterEach(async () => {
        await cleanupAllFixtures(page);
    });

    test.afterAll(async () => {
        await page.close();
    });

    /** Locator for the override summary stat cell whose label matches `name`. */
    function statNum(name: RegExp): ReturnType<Page['locator']> {
        return page
            .locator('.stat-cell')
            .filter({ has: page.locator('.stat-lbl', { hasText: name }) })
            .locator('.stat-num');
    }

    async function openWizardOnProtocol(protocolId: string, runName: string): Promise<void> {
        await page.goto(await projectUrl(page, PROJECT_ID));
        await page.getByRole('button', { name: /^All Runs$/i }).click();
        await page.getByRole('button', { name: /\+ New Run/i }).click();
        await expect(page.getByRole('heading', { name: /Step 1 · Name your run/i })).toBeVisible();
        const nameInput = page.locator('#run-name');
        await nameInput.click();
        await nameInput.fill(runName);
        await expect(nameInput).toHaveValue(runName);
        const continueBtn = page.getByRole('button', { name: /^Continue/ });
        await expect(continueBtn).toBeEnabled();
        await continueBtn.click();
        await page.locator('#proto-pick').selectOption(protocolId);
        await expect(page.getByRole('button', { name: /^Continue/ })).toBeEnabled();
        await page.getByRole('button', { name: /^Continue/ }).click();
    }

    // ── Scenario 1 ────────────────────────────────────────────────────────────
    test('1. linear chain, no roles — value override goes through', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's1-linear-noroles', {
            graph: buildGraph({ unitOpCount: 3, topology: 'linear' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s1`);

        await expect(page.locator('.role-context')).toHaveCount(0);
        await expect(page.locator('.role-group')).toHaveCount(0);

        const inputs = page.locator('input[type="number"]');
        await inputs.nth(1).fill('99');
        await expect(statNum(/^Value$/i)).not.toHaveText('0');
    });

    // ── Scenario 2 ────────────────────────────────────────────────────────────
    test('2. single role (one swimlane) — degenerate path still applies', async () => {
        const roles: RoleSpec[] = [{ id: 'role-op', name: 'Operator', color: '#B96B17' }];
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's2-single-role', {
            roles,
            buildWithResolvedRoles: (resolved) =>
                buildGraph({ roles: resolved, unitOpCount: 2 }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s2`);

        await expect(page.locator('.role-context')).toHaveCount(0);
        await expect(page.locator('.role-group')).toHaveCount(0);
    });

    // ── Scenario 3 ────────────────────────────────────────────────────────────
    test('3. multi-role (2 roles) — context bar + role groups + preserved overrides', async () => {
        const roles: RoleSpec[] = [
            { id: 'role-op', name: 'Operator', color: '#B96B17' },
            { id: 'role-sup', name: 'Senior Operator', color: '#5C6BC0' },
        ];
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's3-multi-2', {
            roles,
            buildWithResolvedRoles: (resolved) =>
                buildGraph({
                    roles: resolved,
                    unitOpsByRole: {
                        [resolved[0].id]: 1,
                        [resolved[1].id]: 1,
                    },
                }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s3`);

        await expect(page.locator('.role-context')).toBeVisible();
        await expect(page.locator('.role-group-head')).toHaveCount(2);

        await page.locator('input[type="number"]').first().fill('50');
        await page.locator('.role-group-head').nth(1).click();
        await expect(page.getByText(/Role 2 of 2/i)).toBeVisible();
        await page.locator('input[type="number"]').first().fill('77');
        await page.locator('.role-group-head').nth(0).click();
        await expect(page.locator('input[type="number"]').first()).toHaveValue('50');
    });

    // ── Scenario 4 — multi-role (3) ───────────────────────────────────────────
    test('4. multi-role (3 roles) — arrow nav + jump-via-aside-head', async () => {
        const roles: RoleSpec[] = [
            { id: 'r1', name: 'Operator', color: '#B96B17' },
            { id: 'r2', name: 'Senior Operator', color: '#5C6BC0' },
            { id: 'r3', name: 'QC Reviewer', color: '#8E5BA8' },
        ];
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's4-multi-3', {
            roles,
            buildWithResolvedRoles: (resolved) =>
                buildGraph({
                    roles: resolved,
                    unitOpsByRole: {
                        [resolved[0].id]: 2,
                        [resolved[1].id]: 1,
                        [resolved[2].id]: 1,
                    },
                }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s4`);

        await expect(page.locator('.role-group-head')).toHaveCount(3);
        await page.getByRole('button', { name: /Next role/i }).click();
        await expect(page.getByText(/Role 2 of 3/i)).toBeVisible();
        await page.locator('.role-group-head').nth(2).click();
        await expect(page.getByText(/Role 3 of 3/i)).toBeVisible();
    });

    // ── Scenario 5 ────────────────────────────────────────────────────────────
    // Equipment swap requires seeded org equipment (≥2 items) + a UO with one
    // already in use, so the picker can target a different one. Adding that
    // infrastructure is out of scope for this initial commit.
    // TODO: extend fixtures with `seedOrgEquipment(page, count)` and a
    // `withEquipment` flag on `buildGraph`; then assert the Equipment stat = 1
    // after picking a different equipment in the modal.
    test.skip(
        '5. equipment swap only — Equipment stat = 1, Value = 0',
        async () => {},
    );

    // ── Scenario 6 ────────────────────────────────────────────────────────────
    test('6. add parameter — Added stat = 1; row tagged ADDED', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's6-add-param', {
            graph: buildGraph({ unitOpCount: 1, topology: 'linear' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s6`);

        await page.locator('summary', { hasText: /ADD \/ EDIT SCHEMA/i }).first().click();
        await page.getByRole('button', { name: /\+ Add Parameter/i }).click();
        const schemaInputs = page.locator('input.schema-input');
        const newRowKey = schemaInputs.nth(2);
        const newRowTitle = schemaInputs.nth(3);
        await newRowKey.fill('volume_ml');
        await newRowTitle.fill('Volume mL');
        await newRowTitle.blur();

        await expect(statNum(/^Added$/i)).not.toHaveText('0');
        await expect(page.locator('.row-tag-amber', { hasText: /\+ ADDED/i })).toBeVisible();
    });

    // ── Scenario 7 ────────────────────────────────────────────────────────────
    test('7. remove parameter — Removed stat ≥ 1', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's7-remove-param', {
            graph: buildGraph({
                unitOpCount: 1,
                topology: 'linear',
                uoDefaults: {
                    params: { temperature: 25, pH: 7 },
                    paramSchema: {
                        type: 'object',
                        properties: {
                            temperature: { type: 'number', title: 'Temperature' },
                            pH: { type: 'number', title: 'pH' },
                        },
                    },
                },
            }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s7`);

        const removeBtn = page.locator('button[aria-label^="Remove "]').first();
        await removeBtn.click();

        await expect(statNum(/^Removed$/i)).not.toHaveText('0');
    });

    // ── Scenario 8 ────────────────────────────────────────────────────────────
    test('8. schema edit — SCHEMA tag appears in aside', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's8-schema-edit', {
            graph: buildGraph({ unitOpCount: 1, topology: 'linear' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s8`);

        // Edit the title of the existing 'temperature' param — value unchanged
        // → produces a SCHEMA edit (not VALUE, not ADDED).
        await page.locator('summary', { hasText: /ADD \/ EDIT SCHEMA/i }).first().click();
        const labelInput = page.locator('input.schema-input').nth(1);
        await labelInput.fill('Reaction Temperature');
        await labelInput.blur();

        await expect(page.locator('.diff-tag.tag-schema').first()).toBeVisible();
    });

    // ── Scenario 9 ────────────────────────────────────────────────────────────
    test('9. instruction edit — INSTRUCTION tag + rendered preview', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's9-instr-edit', {
            graph: buildGraph({ unitOpCount: 1, topology: 'linear' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s9`);

        await page.getByRole('button', { name: /Edit instructions/i }).first().click();
        const textarea = page.locator('.instructions-editor textarea').first();
        await textarea.fill('Anneal at {{temperature}}°C overnight');
        await textarea.blur();

        await expect(page.locator('.diff-tag.tag-instruction').first()).toBeVisible();
        await expect(page.locator('.rendered-template').first()).toContainText(/Anneal at/i);
    });

    // ── Scenario 10 ───────────────────────────────────────────────────────────
    test('10. forked graph — branches render as cards', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's10-fork', {
            graph: buildGraph({ unitOpCount: 3, topology: 'fork' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s10`);

        await expect(page.locator('article.uo-card')).toHaveCount(3);
        await page.locator('input[type="number"]').nth(2).fill('42');

        await expect(statNum(/^Value$/i)).not.toHaveText('0');
    });

    // ── Scenario 11 ───────────────────────────────────────────────────────────
    test('11. empty graph — empty state shown; Continue still progresses', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's11-empty', {
            graph: buildGraph({ topology: 'empty' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s11`);

        await expect(page.locator('.cards-column .empty')).toBeVisible();
        await expect(page.getByText(/No unit ops in this protocol/i)).toBeVisible();
        await page.getByRole('button', { name: /^Continue/ }).click();
        await expect(page.getByRole('heading', { name: /Assign team members/i })).toBeVisible();
    });

    // ── Scenario 12 ───────────────────────────────────────────────────────────
    test('12. Skip · use defaults — bypasses save dialog, review shows defaults', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's12-skip-defaults', {
            graph: buildGraph({ unitOpCount: 2, topology: 'linear' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s12`);

        await page.locator('input[type="number"]').first().fill('999');
        await page.getByRole('button', { name: /Skip · use defaults/i }).click();
        // Skip lands on Step 4 (Assignees), not Review — save dialog does NOT appear.
        await expect(page.locator('.save-dialog, [role="dialog"]').filter({ hasText: /Save as v/i }))
            .toHaveCount(0);
        await expect(page.getByRole('heading', { name: /Assign team members/i })).toBeVisible();
        await page.getByRole('button', { name: /Skip · assign later/i }).click();
        await expect(page.getByText(/uses protocol defaults/i)).toBeVisible();
    });

    // ── Scenario 13 ───────────────────────────────────────────────────────────
    test('13. Save as v{N+1} — publishes new version and advances', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's13-save-as-v2', {
            graph: buildGraph({ unitOpCount: 1, topology: 'linear' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s13`);

        await page.locator('input[type="number"]').first().fill('77');
        await page.getByRole('button', { name: /Continue to review|^Continue/ }).click();
        // SaveAsNewVersionDialog appears
        const saveAsBtn = page.getByRole('button', { name: /Save as v2/i });
        await expect(saveAsBtn).toBeVisible();
        await saveAsBtn.click();
        await expect(page.getByRole('heading', { name: /Assign team members/i })).toBeVisible({
            timeout: 10000,
        });
    });

    // ── Scenario 14 ───────────────────────────────────────────────────────────
    test('14. forExperiment locked — experiment dropdown disabled', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's14-for-experiment', {
            graph: buildGraph({ unitOpCount: 1, topology: 'linear' }),
        });
        const expId = await seedExperimentForFixture(
            page, fx, PROJECT_ID, `${FIXTURE_PREFIX} exp-s14`,
        );

        await page.goto(await experimentUrl(page, expId));
        await page.getByRole('button', { name: /\+ New Run/i }).click();
        await expect(
            page.getByRole('heading', { name: new RegExp(`New Run for ${FIXTURE_PREFIX} exp-s14`) }),
        ).toBeVisible();
        await expect(page.locator('#run-experiment')).toBeDisabled();
    });

    // ── Scenario 15 ───────────────────────────────────────────────────────────
    test('15. discard-on-close — ConfirmDialog flows', async () => {
        const fx = await seedScenarioProtocol(page, PROJECT_ID, 's15-discard', {
            graph: buildGraph({ unitOpCount: 1, topology: 'linear' }),
        });
        await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s15`);

        // Make a change so close prompts confirm
        await page.locator('input[type="number"]').first().fill('123');
        await page.getByRole('button', { name: /^Cancel$/ }).click();

        const dialog = page.getByRole('dialog').filter({ hasText: /Discard changes\?/i });
        await expect(dialog).toBeVisible();
        // First flow: Keep editing dismisses dialog, wizard stays open
        await dialog.getByRole('button', { name: /Keep editing|Cancel/i }).first().click();
        await expect(dialog).toBeHidden();
        // Wizard still open + still on Step 3 (parameters) — uo-card visible.
        await expect(page.locator('article.uo-card').first()).toBeVisible();

        // Second flow: Cancel → Discard closes the wizard
        await page.getByRole('button', { name: /^Cancel$/ }).click();
        const dialog2 = page.getByRole('dialog').filter({ hasText: /Discard changes\?/i });
        await expect(dialog2).toBeVisible();
        await dialog2.getByRole('button', { name: /^Discard$/ }).click();
        await expect(page.getByRole('heading', { name: /^New Run/i })).toBeHidden();
    });

    // ── Scenario 16 ───────────────────────────────────────────────────────────
    // Same equipment-swap infrastructure gap as scenario 5.
    // TODO: once `seedOrgEquipment` and `withEquipment: true` exist, build a
    // 2-role graph, swap equipment under role B while role A is active, and
    // assert the global aside Equipment stat = 1 across roles.
    test.skip(
        '16. multi-role + swap on inactive role — global aside reflects swap',
        async () => {},
    );

    // ── Scenario 17 ───────────────────────────────────────────────────────────
    // Requires a protocol with v1 + v2 published; `seedScenarioProtocol`
    // currently publishes v1 only.
    // TODO: extend with `seedExtraVersion(fixture, graphPatch)` that PUTs
    // `?save_as_draft=true` then POSTs `/publish-draft`, then drive the
    // Step 2 ↳ Compare versions disclosure and the resulting drawer.
    test.skip(
        '17. compare versions drawer — opens, renders, returns without state loss',
        async () => {},
    );
});
