import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate } from './helpers/auth';
import {
  SEED,
  createExperimentViaApi,
  createRunViaApi,
  getProjectProtocols,
  cleanupE2eExperiments,
} from './helpers/experiment';
import { projectUrl, experimentUrl } from './helpers/slug-urls';

/**
 * F-0063: Experiments — Run Organization Under Hypotheses
 *
 * E2E tests for the full experiment lifecycle: create, view, assign runs,
 * add notes, and archive. Uses timestamp-suffixed names for isolation.
 */
test.use({ viewport: { width: 1280, height: 720 } });
test.describe.configure({ mode: 'serial' });

const PROJECT_ID = SEED.PROJECT_MAB_ID;

test.describe('Experiments — Full Workflow', () => {
  let page: Page;
  const ts = Date.now();

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await loginAndNavigate(page, 'admin');
    await cleanupE2eExperiments(page, PROJECT_ID);
  });

  test.afterAll(async () => {
    try {
      await cleanupE2eExperiments(page, PROJECT_ID);
    } catch {
      // best-effort
    }
    await page.close();
  });

  test('create experiment from project page', async () => {
    await page.goto(`${await projectUrl(page, PROJECT_ID)}?tab=experiments`);
    await page.waitForLoadState('networkidle');

    // Click "+ New Experiment"
    const createBtn = page.getByRole('button', { name: /new experiment/i });
    await expect(createBtn).toBeVisible({ timeout: 5000 });
    await createBtn.click();

    // Fill the modal
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });
    await dialog.getByLabel('Name').fill(`E2E Exp ${ts}`);
    await dialog.locator('textarea').fill('Testing MOI values');

    // Submit
    await dialog.locator('button', { hasText: 'Create' }).click();

    // Should redirect to experiment detail page
    await page.waitForURL(/\/experiments\//, { timeout: 10000 });

    // Verify detail page content
    await expect(page.locator('input[placeholder="Experiment name"]')).toHaveValue(`E2E Exp ${ts}`, { timeout: 10000 });
    await expect(page.locator('textarea[placeholder="Add a brief description..."]')).toHaveValue(/Testing MOI values/);
    await expect(page.getByRole('heading', { name: /Notes/ })).toBeVisible();
  });

  test('experiment detail page shows runs and supports notes', async () => {
    const protocols = await getProjectProtocols(page, PROJECT_ID);
    const protocol = protocols[0];

    const expId = await createExperimentViaApi(page, `E2E Detail ${ts}`, PROJECT_ID, 'Detail testing');
    const runId = await createRunViaApi(page, `E2E Run Alpha ${ts}`, PROJECT_ID, protocol.id, expId);

    await page.goto(await experimentUrl(page, expId));
    await page.waitForLoadState('networkidle');

    // Verify run appears (use td locator to avoid mobile card duplicate)
    await expect(page.getByRole('heading', { name: /Runs \(1\)/ })).toBeVisible({ timeout: 10000 });
    await expect(page.locator('td', { hasText: `E2E Run Alpha ${ts}` }).first()).toBeVisible();

    // Add a note
    const noteInput = page.getByPlaceholder(/add a note/i);
    await noteInput.fill('Observed consistent pH');
    // Click the Add button next to the note input (not "Add Existing")
    const noteSection = page.locator('div', { has: noteInput });
    await noteSection.locator('button', { hasText: /^Add$/ }).click();

    // Verify note appears
    await expect(page.getByText('Observed consistent pH')).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole('heading', { name: /Notes \(1\)/ })).toBeVisible();
  });

  test('experiments tab shows experiment with inline runs', async () => {
    const protocols = await getProjectProtocols(page, PROJECT_ID);
    const protocol = protocols[0];

    const expId = await createExperimentViaApi(page, `E2E Tab ${ts}`, PROJECT_ID);
    await createRunViaApi(page, `E2E TabRun1 ${ts}`, PROJECT_ID, protocol.id, expId);
    await createRunViaApi(page, `E2E TabRun2 ${ts}`, PROJECT_ID, protocol.id, expId);

    await page.goto(`${await projectUrl(page, PROJECT_ID)}?tab=experiments`);
    await page.waitForLoadState('networkidle');

    // Verify experiment appears
    const expRow = page.locator('tr', { hasText: `E2E Tab ${ts}` });
    await expect(expRow).toBeVisible({ timeout: 5000 });

    // Click to show inline runs
    await expRow.click();
    await page.waitForTimeout(500);
    // Runs appear in the inline RunsTab below — check table cells (visible on desktop)
    await expect(page.locator('td', { hasText: `E2E TabRun1 ${ts}` }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('td', { hasText: `E2E TabRun2 ${ts}` }).first()).toBeVisible();
  });

  test('all runs tab shows experiment column', async () => {
    // Uses experiment created in previous test
    await page.goto(`${await projectUrl(page, PROJECT_ID)}?tab=runs`);
    await page.waitForLoadState('networkidle');

    // Verify column header
    await expect(page.locator('th', { hasText: 'Experiment' })).toBeVisible({ timeout: 5000 });

    // Verify a linked run shows the experiment name
    const linkedRow = page.locator('tr', { hasText: `E2E TabRun1 ${ts}` }).first();
    await expect(linkedRow.getByRole('link', { name: `E2E Tab ${ts}` })).toBeVisible({ timeout: 5000 });
  });

  test('assign standalone run to experiment', async () => {
    const protocols = await getProjectProtocols(page, PROJECT_ID);
    const protocol = protocols[0];

    const expId = await createExperimentViaApi(page, `E2E AssignTarget ${ts}`, PROJECT_ID);
    await createRunViaApi(page, `E2E Standalone ${ts}`, PROJECT_ID, protocol.id);

    await page.goto(`${await projectUrl(page, PROJECT_ID)}?tab=runs`);
    await page.waitForLoadState('networkidle');

    // Find the standalone run and click Assign
    const row = page.locator('tr', { hasText: `E2E Standalone ${ts}` }).first();
    const assignBtn = row.locator('button', { hasText: 'Assign' });
    await expect(assignBtn).toBeVisible({ timeout: 5000 });
    await assignBtn.click();

    // Modal should appear
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog.getByRole('heading', { name: 'Assign to Experiment' })).toBeVisible({ timeout: 5000 });

    // Select experiment
    await dialog.locator('#assign-exp-select').selectOption({ label: `E2E AssignTarget ${ts}` });

    // Confirm
    await dialog.locator('button', { hasText: 'Assign' }).click();

    // Verify toast
    await expect(page.getByText(/assigned to/i)).toBeVisible({ timeout: 5000 });

    // Verify update
    await page.waitForTimeout(1500);
    const updatedRow = page.locator('tr', { hasText: `E2E Standalone ${ts}` }).first();
    await expect(updatedRow.getByRole('link', { name: `E2E AssignTarget ${ts}` })).toBeVisible({ timeout: 5000 });
  });

  test('create run within experiment via experiments tab', async () => {
    const expId = await createExperimentViaApi(page, `E2E EmptyExp ${ts}`, PROJECT_ID);

    await page.goto(`${await projectUrl(page, PROJECT_ID)}?tab=experiments`);
    await page.waitForLoadState('networkidle');

    // Select the empty experiment
    await page.locator('tr', { hasText: `E2E EmptyExp ${ts}` }).click();

    // Click Create Run
    await expect(page.getByText("doesn't have any run data")).toBeVisible({ timeout: 5000 });
    await page.getByRole('button', { name: '+ Create Run' }).click();

    // Fill modal
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog.getByRole('heading', { name: /New Run for/ })).toBeVisible({ timeout: 5000 });
    await dialog.getByLabel('Name').fill(`E2E FromTab ${ts}`);

    const protocolSelect = dialog.locator('#run-protocol-select');
    const options = await protocolSelect.locator('option').allTextContents();
    const firstProtocol = options.find((o) => o && o !== 'Select a protocol');
    if (firstProtocol) {
      await protocolSelect.selectOption({ label: firstProtocol });
    }

    await dialog.locator('button', { hasText: 'Create' }).click();

    // Should navigate to run page
    await page.waitForURL(/\/runs\//, { timeout: 10000 });
  });

  test('archive experiment cascades to runs', async () => {
    const protocols = await getProjectProtocols(page, PROJECT_ID);
    const protocol = protocols[0];

    const expId = await createExperimentViaApi(page, `E2E Archive ${ts}`, PROJECT_ID);
    const runId = await createRunViaApi(page, `E2E ArchiveRun ${ts}`, PROJECT_ID, protocol.id, expId);

    // Archive via API
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const resp = await page.request.fetch(`http://localhost:8000/experiments/${expId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBe(200);

    // Verify experiment is archived
    const expResp = await page.request.fetch(`http://localhost:8000/experiments/${expId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const expData = await expResp.json();
    expect(expData.status).toBe('ARCHIVED');

    // Verify run is also archived
    const runResp = await page.request.fetch(`http://localhost:8000/runs/${runId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const runData = await runResp.json();
    expect(runData.status).toBe('ARCHIVED');
  });
});
