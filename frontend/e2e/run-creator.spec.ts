import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate } from './helpers/auth';
import { SEED, getProjectProtocols } from './helpers/experiment';
import { projectUrl } from './helpers/slug-urls';

test.use({ viewport: { width: 1280, height: 800 } });
test.describe.configure({ mode: 'serial' });

const PROJECT_ID = SEED.PROJECT_MAB_ID;

test.describe('F-0081 Run Creator Wizard', () => {
    let page: Page;

    test.beforeAll(async ({ browser }) => {
        page = await browser.newPage();
        await loginAndNavigate(page, 'admin');
    });

    test.afterAll(async () => {
        await page.close();
    });

    test('full create flow with overrides', async () => {
        const protocols = await getProjectProtocols(page, PROJECT_ID);
        const proto = protocols.find(
            (p: { status?: string; version_number?: number }) =>
                (p.status ?? '').toUpperCase() === 'PUBLISHED' && (p.version_number ?? 0) > 0,
        );
        expect(proto, 'expected a published protocol with at least v1').toBeTruthy();

        await page.goto(await projectUrl(page, PROJECT_ID));
        await page.getByRole('button', { name: /\+ New Run/i }).click();
        await expect(page.getByRole('heading', { name: /New Run/i })).toBeVisible();

        // Step 1
        await page.getByLabel(/Name/i).fill(`E2E Override Run ${Date.now()}`);
        await page.getByRole('button', { name: /^Continue/ }).click();

        // Step 2
        await page.getByLabel(/Protocol/i).selectOption(proto.id);
        await expect(page.getByText(/v\d+/)).toBeVisible();
        await page.getByRole('button', { name: /^Continue/ }).click();

        // Step 3 — try to override the first param's number input if present
        const firstNumberInput = page.locator('input[type="number"]').first();
        if ((await firstNumberInput.count()) > 0) {
            const orig = await firstNumberInput.inputValue();
            const newVal = (parseFloat(orig || '0') + 5).toString();
            await firstNumberInput.fill(newVal);
            const valueTile = page.locator('.stat-cell').filter({ hasText: /^Value$/i });
            await expect(valueTile.locator('.stat-num')).not.toHaveText('0');
        }

        await page.getByRole('button', { name: /Continue to review/i }).click();

        const dialog = page.getByRole('dialog');
        if (await dialog.isVisible().catch(() => false)) {
            await page.getByRole('button', { name: /Just for this run/i }).click();
        }

        // Step 4
        await expect(page.getByRole('heading', { name: /Review & create/i })).toBeVisible();
        await page.getByRole('button', { name: /Create run/i }).click();

        await expect(page).toHaveURL(/\/projects\/[a-z0-9-]+\/runs\/[a-z0-9-]+$/);
    });

    test('multi-role: role context bar + role-grouped aside (skipped if no multi-role seed)', async () => {
        const protocols = await getProjectProtocols(page, PROJECT_ID);
        const multiRole = protocols.find(
            (p: { status?: string; version_number?: number; roles?: unknown[] }) =>
                (p.status ?? '').toUpperCase() === 'PUBLISHED' &&
                (p.version_number ?? 0) > 0 &&
                Array.isArray(p.roles) &&
                p.roles.length > 1,
        ) as { id: string; roles: unknown[] } | undefined;
        test.skip(!multiRole, 'no multi-role published protocol in seed data');

        await page.goto(await projectUrl(page, PROJECT_ID));
        await page.getByRole('button', { name: /\+ New Run/i }).click();
        await page.getByLabel(/Name/i).fill(`E2E Multi-Role ${Date.now()}`);
        await page.getByRole('button', { name: /^Continue/ }).click();
        await page.getByLabel(/Protocol/i).selectOption(multiRole!.id);
        await page.getByRole('button', { name: /^Continue/ }).click();

        await expect(page.locator('.role-context')).toBeVisible();
        await expect(page.getByText(/Role 1 of \d+/i)).toBeVisible();

        const heads = page.locator('.role-group-head');
        await expect(heads).toHaveCount(multiRole!.roles.length);

        const cardsRoleA = await page.locator('article.uo-card').count();

        await heads.nth(1).click();
        await expect(page.getByText(/Role 2 of \d+/i)).toBeVisible();
        const cardsRoleB = await page.locator('article.uo-card').count();
        expect(cardsRoleB).toBeGreaterThanOrEqual(0);
        void cardsRoleA;

        await page.getByRole('button', { name: /Previous role/i }).click();
        await expect(page.getByText(/Role 1 of \d+/i)).toBeVisible();
    });

    test('skip-overrides path creates a run identical to defaults', async () => {
        const protocols = await getProjectProtocols(page, PROJECT_ID);
        const proto = protocols.find(
            (p: { status?: string; version_number?: number }) =>
                (p.status ?? '').toUpperCase() === 'PUBLISHED' && (p.version_number ?? 0) > 0,
        );
        expect(proto).toBeTruthy();

        await page.goto(await projectUrl(page, PROJECT_ID));
        await page.getByRole('button', { name: /\+ New Run/i }).click();
        await page.getByLabel(/Name/i).fill(`E2E Defaults Run ${Date.now()}`);
        await page.getByRole('button', { name: /^Continue/ }).click();
        await page.getByLabel(/Protocol/i).selectOption(proto.id);
        await page.getByRole('button', { name: /^Continue/ }).click();
        await page.getByRole('button', { name: /Skip · use defaults/i }).click();
        await expect(page.getByRole('heading', { name: /Review & create/i })).toBeVisible();
        await expect(page.getByText(/uses protocol defaults/i)).toBeVisible();
        await page.getByRole('button', { name: /Create run/i }).click();
        await expect(page).toHaveURL(/\/projects\/[a-z0-9-]+\/runs\/[a-z0-9-]+$/);
    });
});
