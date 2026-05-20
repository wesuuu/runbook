import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate, loginViaApi, TEST_USERS } from '../helpers/auth';
import {
    SEED,
    createProtocolViaApi,
    forceCleanupProtocol,
    updateProtocolGraph,
    buildTestGraph,
} from '../helpers/protocol';
import { API_BASE } from '../helpers/apiBase';
import { runUrl } from '../helpers/slug-urls';

/**
 * F-0087 — GLP run sign-off flow exercised against the live UI.
 *
 * Builds a GLP-approved protocol, creates a run from it, starts the run as
 * admin (the operator), and walks through the OPERATOR / SD / QAU sign-offs
 * required by §58.33 / §58.35 before closing the run. The OPERATOR sign-off
 * is done through the SignoffBlock UI so we get end-to-end coverage on the
 * run page; SD and QAU are posted via API to keep the test single-user where
 * possible (the run-page UI is identical for all three roles — same modal,
 * same endpoint).
 *
 * Requires admin, upstream.lead, and scientist2 to have non-null
 * signature_full_path (seeded for the F-0087 work).
 */

const UPSTREAM_LEAD_ID = '20000000-0000-0000-0000-000000000002';
const SCIENTIST2_ID = '20000000-0000-0000-0000-000000000005';

test.use({ viewport: { width: 1280, height: 800 } });

async function apiPost(
    page: Page,
    path: string,
    body?: Record<string, unknown>,
): Promise<{ status: number; data: Record<string, unknown> }> {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const resp = await page.request.post(`${API_BASE}${path}`, {
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
        },
        data: body ?? {},
    });
    let data: Record<string, unknown> = {};
    try {
        data = await resp.json();
    } catch {
        /* no body */
    }
    return { status: resp.status(), data };
}

async function apiPatch(
    page: Page,
    path: string,
    body: Record<string, unknown>,
): Promise<{ status: number; data: Record<string, unknown> }> {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const resp = await page.request.patch(`${API_BASE}${path}`, {
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
        },
        data: body,
    });
    let data: Record<string, unknown> = {};
    try {
        data = await resp.json();
    } catch {
        /* no body */
    }
    return { status: resp.status(), data };
}

async function apiGet(
    page: Page,
    path: string,
): Promise<{ status: number; data: Record<string, unknown> }> {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const resp = await page.request.get(`${API_BASE}${path}`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    let data: Record<string, unknown> = {};
    try {
        data = await resp.json();
    } catch {
        /* no body */
    }
    return { status: resp.status(), data };
}

async function apiDelete(page: Page, path: string): Promise<void> {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    await page.request.delete(`${API_BASE}${path}`, {
        headers: { Authorization: `Bearer ${token}` },
    });
}

test.describe('GLP — run sign-off flow', () => {
    let page: Page;
    const createdRunIds: string[] = [];
    const createdProtocolIds: string[] = [];

    test.beforeEach(async ({ page: p }) => {
        page = p;
    });

    test.afterEach(async () => {
        await loginAndNavigate(page, 'admin');
        for (const id of createdRunIds.splice(0)) {
            await apiDelete(page, `/runs/${id}`).catch(() => undefined);
        }
        for (const id of createdProtocolIds.splice(0)) {
            await forceCleanupProtocol(page, id);
        }
    });

    test('operator signs run via UI, SD + QAU sign via API, run closes COMPLETED', async () => {
        // --- Step 1: admin authors a GLP protocol with SD + QAU required ---
        await loginAndNavigate(page, 'admin');
        const proto = await createProtocolViaApi(
            page,
            SEED.PROJECT_MAB_ID,
            `E2E GLP run signoff ${Date.now()}`,
        );
        const protocolId = proto.id as string;
        createdProtocolIds.push(protocolId);

        const { graph } = buildTestGraph(2);
        await updateProtocolGraph(page, protocolId, {
            ...graph,
            glpSettings: {
                require_study_director: true,
                study_director_user_id: UPSTREAM_LEAD_ID,
                require_qau: true,
                qau_mode: 'SPECIFIC_USER',
                qau_user_id: SCIENTIST2_ID,
                operator_attestation_text:
                    'I attest as Operator that the steps were executed as recorded.',
                study_director_attestation_text:
                    'I attest as Study Director under 21 CFR §58.33.',
                qau_attestation_text:
                    'I attest as QAU under 21 CFR §58.35.',
            },
        });

        // --- Step 2: designate + submit + collect protocol sign-offs ---
        let resp = await apiPost(
            page,
            `/protocols/${protocolId}/designate-approval`,
            { requires_approval: true },
        );
        expect(resp.status).toBe(200);

        resp = await apiPost(
            page,
            `/protocols/${protocolId}/submit-for-approval`,
            { requested_user_ids: [UPSTREAM_LEAD_ID, SCIENTIST2_ID] },
        );
        expect(resp.status).toBe(200);

        await loginViaApi(page, 'upstreamLead');
        resp = await apiPost(
            page,
            `/protocols/${protocolId}/signoffs`,
            {
                role: 'STUDY_DIRECTOR',
                action: 'APPROVED',
                attestation: 'SD attest for run-signoff e2e.',
            },
        );
        expect(resp.status).toBe(201);

        await loginViaApi(page, 'scientist2');
        resp = await apiPost(
            page,
            `/protocols/${protocolId}/signoffs`,
            {
                role: 'QAU',
                action: 'APPROVED',
                attestation: 'QAU attest for run-signoff e2e.',
            },
        );
        expect(resp.status).toBe(201);

        // Admin finalises the protocol via /approve now that SD + QAU signed.
        await loginViaApi(page, 'admin');
        const approveResp = await apiPost(
            page,
            `/protocols/${protocolId}/approve`,
            { comment: 'All signoffs collected.' },
        );
        expect(approveResp.status).toBe(200);
        const protoCheck = await apiGet(page, `/protocols/${protocolId}`);
        expect(protoCheck.data.status).toBe('APPROVED');

        // --- Step 3: admin creates a run from the approved protocol ---
        const runResp = await apiPost(page, `/runs`, {
            name: `E2E GLP run ${Date.now()}`,
            project_id: SEED.PROJECT_MAB_ID,
            protocol_id: protocolId,
        });
        expect(runResp.status).toBe(201);
        const runId = runResp.data.id as string;
        createdRunIds.push(runId);

        // --- Step 4: start the run (admin becomes the operator via started_by_id) ---
        const stateResp = await apiPatch(page, `/runs/${runId}/state`, {
            state: 'ACTIVE',
        });
        expect(stateResp.status).toBe(200);
        expect(stateResp.data.status).toBe('ACTIVE');

        // --- Step 5: operator signs via SignoffBlock UI on the run page ---
        await loginViaApi(page, 'admin');
        await page.goto(await runUrl(page, runId));
        await page.waitForLoadState('networkidle');

        // Wait for the GLP sign-offs heading to confirm the section rendered.
        await expect(
            page.getByRole('heading', { name: /GLP Sign-offs/i }),
        ).toBeVisible({ timeout: 10_000 });

        const operatorSignBtn = page.getByRole('button', {
            name: /sign as operator/i,
        });
        await expect(operatorSignBtn).toBeVisible();
        await operatorSignBtn.click();

        const operatorDialog = page.locator('[role="dialog"]');
        await expect(operatorDialog).toBeVisible();
        await operatorDialog
            .locator('textarea')
            .fill('I attest as Operator that the steps were executed as recorded.');
        await operatorDialog
            .getByRole('button', { name: /confirm sign-off/i })
            .click();

        // Operator row flips to "Signed" with admin's email visible.
        await expect(
            page.getByText(TEST_USERS.admin.email, { exact: false }).first(),
        ).toBeVisible();
        // "Sign as OPERATOR" button is gone.
        await expect(operatorSignBtn).toHaveCount(0);

        // --- Step 6: SD signs via API (UI flow already covered in protocol test) ---
        await loginViaApi(page, 'upstreamLead');
        resp = await apiPost(page, `/runs/${runId}/signoffs`, {
            role: 'STUDY_DIRECTOR',
            action: 'APPROVED',
            attestation: 'SD attest on run.',
        });
        expect(resp.status).toBe(201);

        // --- Step 7: QAU signs via API ---
        await loginViaApi(page, 'scientist2');
        resp = await apiPost(page, `/runs/${runId}/signoffs`, {
            role: 'QAU',
            action: 'APPROVED',
            attestation: 'QAU attest on run.',
        });
        expect(resp.status).toBe(201);

        // --- Step 8: completing the run before all sign-offs would 400; after
        // ---          OPERATOR + SD + QAU it should succeed.
        await loginViaApi(page, 'admin');
        const completeResp = await apiPost(page, `/runs/${runId}/complete`, {
            outcome: 'COMPLETED_NORMAL',
            outcome_notes: 'E2E happy path.',
        });
        expect(completeResp.status).toBe(200);
        expect(completeResp.data.status).toBe('COMPLETED');
        expect(completeResp.data.outcome).toBe('COMPLETED_NORMAL');

        // --- Step 9: verify the run page now shows all three signed rows ---
        await page.goto(await runUrl(page, runId));
        await expect(
            page.getByRole('heading', { name: /GLP Sign-offs/i }),
        ).toBeVisible({ timeout: 10_000 });
        await expect(
            page.getByText(TEST_USERS.admin.email, { exact: false }).first(),
        ).toBeVisible();
        await expect(
            page.getByText(TEST_USERS.upstreamLead.email, { exact: false }).first(),
        ).toBeVisible();
        await expect(
            page.getByText(TEST_USERS.scientist2.email, { exact: false }).first(),
        ).toBeVisible();
    });

    test('run cannot close until required GLP sign-offs are present', async () => {
        // --- Setup: GLP-approved protocol + run started by admin ---
        await loginAndNavigate(page, 'admin');
        const proto = await createProtocolViaApi(
            page,
            SEED.PROJECT_MAB_ID,
            `E2E GLP close-gate ${Date.now()}`,
        );
        const protocolId = proto.id as string;
        createdProtocolIds.push(protocolId);

        const { graph } = buildTestGraph(1);
        await updateProtocolGraph(page, protocolId, {
            ...graph,
            glpSettings: {
                require_study_director: true,
                study_director_user_id: UPSTREAM_LEAD_ID,
                require_qau: true,
                qau_mode: 'SPECIFIC_USER',
                qau_user_id: SCIENTIST2_ID,
            },
        });

        await apiPost(
            page,
            `/protocols/${protocolId}/designate-approval`,
            { requires_approval: true },
        );
        await apiPost(
            page,
            `/protocols/${protocolId}/submit-for-approval`,
            { requested_user_ids: [UPSTREAM_LEAD_ID, SCIENTIST2_ID] },
        );

        await loginViaApi(page, 'upstreamLead');
        await apiPost(page, `/protocols/${protocolId}/signoffs`, {
            role: 'STUDY_DIRECTOR',
            action: 'APPROVED',
            attestation: 'SD',
        });
        await loginViaApi(page, 'scientist2');
        await apiPost(page, `/protocols/${protocolId}/signoffs`, {
            role: 'QAU',
            action: 'APPROVED',
            attestation: 'QAU',
        });

        await loginViaApi(page, 'admin');
        await apiPost(page, `/protocols/${protocolId}/approve`, {
            comment: 'approve for close-gate test',
        });
        const runResp = await apiPost(page, `/runs`, {
            name: `E2E GLP close-gate ${Date.now()}`,
            project_id: SEED.PROJECT_MAB_ID,
            protocol_id: protocolId,
        });
        const runId = runResp.data.id as string;
        createdRunIds.push(runId);
        await apiPatch(page, `/runs/${runId}/state`, { state: 'ACTIVE' });

        // --- Attempt to close with no sign-offs → 400 SIGNOFF_REQUIRED ---
        const close0 = await apiPost(page, `/runs/${runId}/complete`, {
            outcome: 'COMPLETED_NORMAL',
        });
        expect(close0.status).toBe(400);
        expect(
            (close0.data.detail as Record<string, unknown>).error,
        ).toBe('SIGNOFF_REQUIRED');
        expect(
            (close0.data.detail as Record<string, unknown>).missing_roles,
        ).toEqual(expect.arrayContaining(['OPERATOR', 'STUDY_DIRECTOR', 'QAU']));

        // --- Sign just the operator: still missing SD + QAU ---
        await apiPost(page, `/runs/${runId}/signoffs`, {
            role: 'OPERATOR',
            action: 'APPROVED',
            attestation: 'op',
        });
        const close1 = await apiPost(page, `/runs/${runId}/complete`, {
            outcome: 'COMPLETED_NORMAL',
        });
        expect(close1.status).toBe(400);
        expect(
            (close1.data.detail as Record<string, unknown>).missing_roles,
        ).toEqual(expect.arrayContaining(['STUDY_DIRECTOR', 'QAU']));

        // --- Sign SD + QAU then close → 200 ---
        await loginViaApi(page, 'upstreamLead');
        await apiPost(page, `/runs/${runId}/signoffs`, {
            role: 'STUDY_DIRECTOR',
            action: 'APPROVED',
            attestation: 'sd',
        });
        await loginViaApi(page, 'scientist2');
        await apiPost(page, `/runs/${runId}/signoffs`, {
            role: 'QAU',
            action: 'APPROVED',
            attestation: 'qau',
        });
        await loginViaApi(page, 'admin');
        const close2 = await apiPost(page, `/runs/${runId}/complete`, {
            outcome: 'COMPLETED_NORMAL',
        });
        expect(close2.status).toBe(200);
        expect(close2.data.status).toBe('COMPLETED');
    });
});
