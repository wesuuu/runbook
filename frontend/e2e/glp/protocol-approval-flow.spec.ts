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
import { protocolUrl } from '../helpers/slug-urls';

/**
 * F-0087 Task 41b — full GLP approval flow exercised against the live UI.
 *
 * Designated SD / QAU sign the protocol via SignoffBlock, the creator
 * finalises with /approve, and a non-designated user is rejected at the
 * signoff endpoint. Requires upstream.lead and scientist2 to have non-null
 * signature_full_path (seeded for the F-0087 work; if a future seed drops
 * those signatures, this spec will need an upload-signature setup step).
 */

// Seed user IDs from backend/app/db/seed.py.
const UPSTREAM_LEAD_ID = '20000000-0000-0000-0000-000000000002';
const SCIENTIST2_ID = '20000000-0000-0000-0000-000000000005';

test.use({
    viewport: { width: 1280, height: 800 },
    video: 'on',
});

async function apiPost(
    page: Page,
    path: string,
    body: Record<string, unknown>,
): Promise<{ status: number; data: Record<string, unknown> }> {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'));
    const resp = await page.request.post(`${API_BASE}${path}`, {
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

test.describe('GLP — full protocol approval flow', () => {
    let page: Page;
    const createdProtocolIds: string[] = [];

    test.beforeEach(async ({ page: p }) => {
        page = p;
    });

    test.afterEach(async () => {
        // Cleanup runs as admin to avoid permission issues.
        await loginAndNavigate(page, 'admin');
        for (const id of createdProtocolIds.splice(0)) {
            await forceCleanupProtocol(page, id);
        }
    });

    test('SD + QAU sign via SignoffBlock, creator finalises, non-designated is rejected', async () => {
        // --- Step 1: admin authors a GLP-enabled protocol ---
        await loginAndNavigate(page, 'admin');
        const proto = await createProtocolViaApi(
            page,
            SEED.PROJECT_MAB_ID,
            `E2E GLP approval ${Date.now()}`,
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
                study_director_attestation_text:
                    'I attest as Study Director under 21 CFR §58.33.',
                qau_attestation_text:
                    'I attest as QAU under 21 CFR §58.35.',
            },
        });

        // --- Step 2: designate the protocol as requiring approval, then submit
        // ---           with the SD + QAU as the requested approvers.
        // GLP designation makes them eligible automatically; project APPROVE
        // perms are not required for the SD/QAU pair.
        const designateResp = await apiPost(
            page,
            `/protocols/${protocolId}/designate-approval`,
            { requires_approval: true },
        );
        expect(designateResp.status).toBe(200);

        const submitResp = await apiPost(
            page,
            `/protocols/${protocolId}/submit-for-approval`,
            { requested_user_ids: [UPSTREAM_LEAD_ID, SCIENTIST2_ID] },
        );
        expect(submitResp.status).toBe(200);

        // --- Step 3: SD signs via SignoffBlock UI ---
        await loginViaApi(page, 'upstreamLead');
        await page.goto(await protocolUrl(page, protocolId));
        await page.waitForLoadState('networkidle');
        const signoffBlock = page.locator('[data-testid="protocol-glp-signoffs"]');
        await expect(signoffBlock).toBeVisible();

        const sdSignButton = signoffBlock.getByRole('button', {
            name: /sign as study_director/i,
        });
        await expect(sdSignButton).toBeVisible();
        await sdSignButton.click();

        const sdDialog = page.locator('[role="dialog"]');
        await expect(sdDialog).toBeVisible();
        await sdDialog
            .locator('textarea')
            .fill('I attest as SD that this protocol is GLP-compliant.');
        await sdDialog.getByRole('button', { name: /confirm sign-off/i }).click();

        // SD row flips to "Signed" with signer email visible.
        await expect(
            signoffBlock.getByText(TEST_USERS.upstreamLead.email),
        ).toBeVisible();
        // No more "Sign as STUDY_DIRECTOR" button.
        await expect(sdSignButton).toHaveCount(0);

        // --- Step 4: QAU signs via SignoffBlock UI ---
        await loginViaApi(page, 'scientist2');
        await page.goto(await protocolUrl(page, protocolId));
        await page.waitForLoadState('networkidle');
        const qauSignButton = signoffBlock.getByRole('button', {
            name: /sign as qau/i,
        });
        await expect(qauSignButton).toBeVisible();
        await qauSignButton.click();

        const qauDialog = page.locator('[role="dialog"]');
        await expect(qauDialog).toBeVisible();
        await qauDialog
            .locator('textarea')
            .fill('I attest as QAU that this protocol meets quality requirements.');
        await qauDialog.getByRole('button', { name: /confirm sign-off/i }).click();

        await expect(
            signoffBlock.getByText(TEST_USERS.scientist2.email),
        ).toBeVisible();
        await expect(qauSignButton).toHaveCount(0);

        // --- Step 5: non-designated user is rejected by signoff API ---
        await loginViaApi(page, 'downstreamLead');
        const forbiddenResp = await apiPost(
            page,
            `/protocols/${protocolId}/signoffs`,
            { role: 'STUDY_DIRECTOR', action: 'APPROVED', attestation: 'nope' },
        );
        expect([401, 403]).toContain(forbiddenResp.status);

        // --- Step 6: admin finalises via /approve ---
        await loginAndNavigate(page, 'admin');
        const approveResp = await apiPost(
            page,
            `/protocols/${protocolId}/approve`,
            { comment: 'All signoffs collected.' },
        );
        // /approve either flips PENDING_APPROVAL → APPROVED, or returns 400
        // "Cannot approve: protocol is APPROVED." if the signoff fulfilment
        // chain already finalised the protocol. Either outcome ends with the
        // protocol APPROVED, which is the contract we care about.
        expect([200, 400]).toContain(approveResp.status);

        const protocolResp = await page.request.get(
            `${API_BASE}/protocols/${protocolId}`,
            {
                headers: {
                    Authorization: `Bearer ${await page.evaluate(() =>
                        localStorage.getItem('auth_token'),
                    )}`,
                },
            },
        );
        const refreshed = await protocolResp.json();
        expect(refreshed.status).toBe('APPROVED');
    });
});
