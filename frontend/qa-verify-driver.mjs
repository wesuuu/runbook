// frontend/qa-verify-driver.mjs — F-0066 Protocol Approval QA Verification
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const FRONTEND = 'http://localhost:5183';
const API = 'http://localhost:8010';
const OUT = '/tmp/qa-verify';
mkdirSync(OUT, { recursive: true });

const USERS = {
  admin: { email: 'admin@bioprocess.com', password: 'password123' },
  upstreamLead: { email: 'upstream.lead@bioprocess.com', password: 'password123' },
  viewer: { email: 'viewer@bioprocess.com', password: 'password123' },
};

let adminToken = '';

async function apiCall(page, method, path, data, token) {
  const tk = token || adminToken;
  const opts = { headers: { 'Authorization': `Bearer ${tk}`, 'Content-Type': 'application/json' } };
  if (data) opts.data = data;
  const res = method === 'GET'
    ? await page.request.get(`${API}${path}`, opts)
    : method === 'PUT'
      ? await page.request.put(`${API}${path}`, opts)
      : method === 'DELETE'
        ? await page.request.delete(`${API}${path}`, opts)
        : await page.request.post(`${API}${path}`, opts);
  let body;
  try { body = await res.json(); } catch { body = {}; }
  console.log(`${method} ${path} => ${res.status()}: ${JSON.stringify(body).substring(0, 200)}`);
  return { status: res.status(), body, ok: res.ok() };
}

async function loginUser(page, userKey = 'admin') {
  const { email, password } = USERS[userKey];
  const res = await page.request.post(`${API}/auth/login`, {
    data: { email, password }
  });
  if (!res.ok()) throw new Error(`login failed ${res.status()}`);
  const { access_token } = await res.json();
  if (userKey === 'admin') adminToken = access_token;
  await page.goto(`${FRONTEND}/`);
  await page.evaluate((t) => localStorage.setItem('auth_token', t), access_token);
  await page.goto(`${FRONTEND}/`);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  console.log(`Logged in as ${userKey}`);
  return access_token;
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1024, height: 768 } });
const page = await context.newPage();

const consoleErrors = [];
page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));

await loginUser(page, 'admin');

const PROJECT_ID = '40000000-0000-0000-0000-000000000001';

// Known IDs from seed data
const APPROVED_PROTOCOL_ID = 'cbdcbc9a-5778-4f5b-9b77-2440ae6aac6a'; // Skin Cell Seeding - APPROVED
const DRAFT_PROTOCOL_ID = 'c5682746-f95d-40be-a489-d13a1b53c260'; // Saline Buffer - DRAFT

// ===== SETUP: Ensure project settings and approvers =====
const projRes = await apiCall(page, 'GET', `/projects/${PROJECT_ID}`, null);
const currentSettings = projRes.body.settings || {};
if (!currentSettings.require_protocol_approval) {
  await apiCall(page, 'PUT', `/projects/${PROJECT_ID}`, {
    settings: { ...currentSettings, require_protocol_approval: true }
  });
}

const meRes = await apiCall(page, 'GET', '/auth/me', null);
const ADMIN_ID = meRes.body.id;
console.log(`Admin ID: ${ADMIN_ID}`);

// Ensure admin is a project approver
const existingApproversRes = await apiCall(page, 'GET', `/projects/${PROJECT_ID}/approvers`, null);
const existingApprovers = Array.isArray(existingApproversRes.body) ? existingApproversRes.body : [];
const alreadyApprover = existingApprovers.some(a => a.principal_id === ADMIN_ID && a.permission_level === 'APPROVE');
if (!alreadyApprover) {
  await apiCall(page, 'POST', `/projects/${PROJECT_ID}/approvers`, {
    principal_type: 'USER',
    principal_id: ADMIN_ID
  });
}

// ===== SURFACE 1: Dashboard — PendingApprovalsCard =====
// First submit the DRAFT protocol so there's a pending approval for admin
// Reset it first in case it's already PENDING_APPROVAL
const draftProtoRes = await apiCall(page, 'GET', `/science/protocols/${DRAFT_PROTOCOL_ID}`, null);
let draftStatus = draftProtoRes.body.status;
console.log(`Draft protocol status: ${draftStatus}`);

if (draftStatus === 'DRAFT') {
  const submitRes = await apiCall(page, 'POST', `/science/protocols/${DRAFT_PROTOCOL_ID}/submit-for-approval`, {
    requested_user_ids: [ADMIN_ID]
  });
  if (submitRes.ok) {
    draftStatus = 'PENDING_APPROVAL';
    console.log('Submitted for approval successfully');
  } else {
    console.log(`Submit failed: ${JSON.stringify(submitRes.body)}`);
  }
}

await page.goto(`${FRONTEND}/`);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(2500);
await page.screenshot({ path: `${OUT}/01-dashboard.png`, fullPage: true });
const pendingCard = await page.locator('[data-testid="pending-approvals-card"]').count();
console.log(`01: PendingApprovalsCard visible: ${pendingCard > 0}`);
const pendingRows = await page.locator('[data-testid="pending-approval-row"]').count();
console.log(`01: Pending approval rows: ${pendingRows}`);

// ===== SURFACE 6: Protocol Editor — PENDING_APPROVAL state =====
await page.goto(`${FRONTEND}/protocols/${DRAFT_PROTOCOL_ID}`);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(3000);
await page.screenshot({ path: `${OUT}/02-protocol-pending.png`, fullPage: true });

// Scroll sidebar
await page.evaluate(() => {
  document.querySelectorAll('aside, .overflow-y-auto').forEach(el => el.scrollTop = el.scrollHeight);
});
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/02b-sidebar-pending.png`, fullPage: true });

const approveBtn = page.locator('button').filter({ hasText: /^Approve$/i }).first();
const rejectBtn = page.locator('button').filter({ hasText: /^Reject$/i }).first();
console.log(`02: Approve btn visible: ${await approveBtn.isVisible({ timeout: 3000 }).catch(() => false)}`);
console.log(`02: Reject btn visible: ${await rejectBtn.isVisible({ timeout: 3000 }).catch(() => false)}`);

// Click Approve
if (await approveBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
  await approveBtn.click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${OUT}/03-approve-dialog.png`, fullPage: true });

  // Find signature input
  const sigInputs = await page.locator('[role="dialog"] input[type="text"], [role="dialog"] textarea').all();
  console.log(`03: Signature dialog inputs: ${sigInputs.length}`);
  for (const inp of sigInputs) {
    const ph = await inp.getAttribute('placeholder') || '';
    const label = await inp.getAttribute('aria-label') || '';
    console.log(`  field: placeholder="${ph}" aria-label="${label}"`);
    if (await inp.isEnabled()) {
      await inp.fill('I approve this protocol for use in production. - Admin User');
    }
  }
  await page.screenshot({ path: `${OUT}/03b-signature-filled.png`, fullPage: true });

  // Click confirm Approve in dialog
  const confirmApprove = page.locator('[role="dialog"] button').filter({ hasText: /^Approve$/i }).first();
  const isEnabled = await confirmApprove.isEnabled({ timeout: 2000 }).catch(() => false);
  console.log(`03: Confirm approve button enabled: ${isEnabled}`);
  if (isEnabled) {
    await confirmApprove.click();
    await page.waitForTimeout(2000);
    console.log('03: Clicked Approve confirm button');
  } else {
    // Log all dialog buttons for debugging
    const allBtns = await page.locator('[role="dialog"] button').all();
    for (const b of allBtns) {
      console.log('  dialog btn:', await b.textContent(), '| enabled:', await b.isEnabled());
    }
  }
  await page.screenshot({ path: `${OUT}/03c-after-approve.png`, fullPage: true });
} else {
  // Fall back to API approve
  console.log('03: Using API to approve');
  await apiCall(page, 'POST', `/science/protocols/${DRAFT_PROTOCOL_ID}/approve`, {
    signature_statement: 'I approve this protocol for use in production. - Admin User',
    comment: ''
  });
  await page.reload();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT}/03c-api-approved.png`, fullPage: true });
}

// Scroll sidebar to see approval history
await page.evaluate(() => {
  document.querySelectorAll('aside, .overflow-y-auto').forEach(el => el.scrollTop = el.scrollHeight);
});
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/04-approved-with-history.png`, fullPage: true });

// ===== SURFACE 2: Edit-on-APPROVED — RevertOnEditConfirmDialog =====
// Use the already-APPROVED protocol (Skin Cell Seeding) which has nodes
console.log(`\n=== Testing drag on APPROVED protocol: ${APPROVED_PROTOCOL_ID} ===`);
await page.goto(`${FRONTEND}/protocols/${APPROVED_PROTOCOL_ID}`);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(3500);
await page.screenshot({ path: `${OUT}/05-approved-protocol.png`, fullPage: true });

const flowNodes = await page.locator('.svelte-flow__node').all();
console.log(`05: Canvas nodes: ${flowNodes.length}`);

if (flowNodes.length > 0) {
  // Use a non-swimlane node (avoid type=group which are swimlanes)
  let targetNode = null;
  for (const n of flowNodes) {
    const cls = await n.getAttribute('class') || '';
    if (!cls.includes('svelte-flow__node-group')) {
      targetNode = n;
      break;
    }
  }
  if (!targetNode) targetNode = flowNodes[0];

  const box = await targetNode.boundingBox();
  if (box) {
    console.log(`05: Dragging node at (${box.x.toFixed(0)}, ${box.y.toFixed(0)}) -> (+80, +50)`);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(200);
    await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2 + 30, { steps: 10 });
    await page.waitForTimeout(200);
    await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 50, { steps: 10 });
    await page.waitForTimeout(200);
    await page.mouse.up();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${OUT}/05b-after-drag.png`, fullPage: true });

    const revertDialogCount = await page.locator('[role="dialog"]').count();
    console.log(`05: Revert dialog after drag: ${revertDialogCount}`);

    if (revertDialogCount > 0) {
      const dialogText = await page.locator('[role="dialog"]').first().textContent();
      console.log(`05: Dialog text: ${dialogText?.substring(0, 150)}`);
      await page.screenshot({ path: `${OUT}/05c-revert-dialog.png`, fullPage: true });

      // Cancel — edit should be reverted, status stays APPROVED
      const cancelBtn = page.locator('[role="dialog"] button').filter({ hasText: /cancel/i }).first();
      if (await cancelBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await cancelBtn.click();
        await page.waitForTimeout(1000);
        await page.screenshot({ path: `${OUT}/05d-after-cancel.png`, fullPage: true });
        console.log('05: Cancelled — node should be back in original position');
      }

      // Drag again and confirm (to test the confirm path)
      const box2 = await targetNode.boundingBox();
      if (box2) {
        await page.mouse.move(box2.x + box2.width / 2, box2.y + box2.height / 2);
        await page.mouse.down();
        await page.waitForTimeout(200);
        await page.mouse.move(box2.x + box2.width / 2 + 80, box2.y + box2.height / 2 + 50, { steps: 15 });
        await page.waitForTimeout(200);
        await page.mouse.up();
        await page.waitForTimeout(2000);

        const revertDialog2 = await page.locator('[role="dialog"]').count();
        if (revertDialog2 > 0) {
          const confirmBtn = page.locator('[role="dialog"] button').filter({ hasText: /confirm|proceed|yes|edit/i }).first();
          if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
            await confirmBtn.click();
            await page.waitForTimeout(1000);
            console.log('05: Confirmed edit — status should now be DRAFT');
            await page.screenshot({ path: `${OUT}/05e-after-confirm.png`, fullPage: true });
          } else {
            const btns = await page.locator('[role="dialog"] button').all();
            for (const b of btns) { console.log('  dialog btn:', await b.textContent()); }
          }
        }
      }
    } else {
      // Check if there's a toast or any visible change
      const toastCount = await page.locator('[data-sonner-toast], .toast, [role="alert"]').count();
      console.log(`05: WARN — no revert dialog. Protocol status may already be DRAFT. Toasts: ${toastCount}`);
      // Check current protocol status via API
      const statusRes = await apiCall(page, 'GET', `/science/protocols/${APPROVED_PROTOCOL_ID}`, null);
      console.log(`05: Protocol status via API: ${statusRes.body.status}`);
    }
  }
} else {
  console.log('05: No canvas nodes — taking screenshot');
}

// ===== SURFACE 3: Run gate — PROTOCOL_NOT_APPROVED =====
// Use a protocol that requires approval but is DRAFT
const gateProtoId = DRAFT_PROTOCOL_ID; // now APPROVED (we just approved it)
// Need a different DRAFT protocol
const sampleProtoRes = await apiCall(page, 'GET', '/science/protocols/a9b3c4d5-e6f7-8901-2345-678901234567', null);
// Find a DRAFT protocol with requires_approval via API
const allProtosRes = await apiCall(page, 'GET', `/science/projects/${PROJECT_ID}/protocols`, null);
const protoList = Array.isArray(allProtosRes.body) ? allProtosRes.body : [];
const gateTestProto = protoList.find(p => p.status === 'DRAFT' && p.requires_approval);
let gateTestResult = 'N/A - no DRAFT+requires_approval protocol found';
if (gateTestProto) {
  const blockedRunRes = await apiCall(page, 'POST', '/science/runs', {
    name: 'QA Gate Test Run',
    project_id: PROJECT_ID,
    protocol_id: gateTestProto.id
  });
  gateTestResult = blockedRunRes.status === 400 ? 'PASS' : `FAIL (got ${blockedRunRes.status})`;
  if (blockedRunRes.body?.detail?.code) console.log(`Gate error code: ${blockedRunRes.body.detail.code}`);
  console.log(`06: Run gate test (${gateTestProto.name}): ${gateTestResult}`);
}

// ===== SURFACE 3b: Create run from already-APPROVED protocol (APPROVED_PROTOCOL_ID = Skin Cell Seeding) =====
// But after we edited it, its status might have changed. Fetch fresh status first
const approvedProtoStatusRes = await apiCall(page, 'GET', `/science/protocols/${APPROVED_PROTOCOL_ID}`, null);
const approvedProtoStatus = approvedProtoStatusRes.body.status;
console.log(`06b: APPROVED protocol status (after drag test): ${approvedProtoStatus}`);

// Find an APPROVED protocol that we didn't drag on
const stillApprovedProto = protoList.find(p => p.status === 'APPROVED' && p.id !== APPROVED_PROTOCOL_ID);
const runProto = stillApprovedProto || (approvedProtoStatus === 'APPROVED' ? { id: APPROVED_PROTOCOL_ID } : null);

let RUN_ID, IS_STRICT;
if (runProto) {
  const runRes = await apiCall(page, 'POST', '/science/runs', {
    name: 'QA Strict Run',
    project_id: PROJECT_ID,
    protocol_id: runProto.id
  });
  console.log(`06b: Create run from APPROVED: status=${runRes.status}, is_strict=${runRes.body.is_strict}`);
  if (runRes.ok) {
    RUN_ID = runRes.body.id;
    IS_STRICT = runRes.body.is_strict;
  } else {
    console.log(`06b: Run creation failed: ${JSON.stringify(runRes.body)}`);
  }
}

// ===== SURFACE 5: Project Settings tab =====
await page.goto(`${FRONTEND}/projects/${PROJECT_ID}?tab=settings`);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(2500);
await page.screenshot({ path: `${OUT}/08-project-settings.png`, fullPage: true });
const approversCard = await page.locator('text=Protocol Approvers').count();
const requireApprovalCheckbox = await page.locator('input[type="checkbox"]').first().isChecked().catch(() => false);
console.log(`08: ProjectProtocolApproversCard visible: ${approversCard > 0}, checkbox checked: ${requireApprovalCheckbox}`);

// Try adding admin as project approver via UI (as a visual test)
const selectEl = page.locator('[data-testid="approver-select"]');
if (await selectEl.isVisible({ timeout: 2000 }).catch(() => false)) {
  const options = await selectEl.evaluate(el => [...el.querySelectorAll('option')].map(o => ({ value: o.value, text: o.text })));
  console.log(`08: Approver select options: ${JSON.stringify(options.filter(o => o.value))}`);
}

// ===== SURFACE 5b: Protocols tab status badges =====
await page.goto(`${FRONTEND}/projects/${PROJECT_ID}?tab=protocols`);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/09-protocols-tab.png`, fullPage: true });
const badges = await page.locator('.rounded-full').allTextContents();
console.log(`09: Status badges: ${JSON.stringify(badges.slice(0, 15))}`);

// ===== SURFACE 7: Org Settings =====
await page.goto(`${FRONTEND}/settings`);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(2000);
await page.screenshot({ path: `${OUT}/10-org-settings.png`, fullPage: true });
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/10b-org-settings-bottom.png`, fullPage: true });
const orgApproversCard = await page.locator('text=Protocol Approvers').count();
console.log(`10: OrgProtocolApproversCard: ${orgApproversCard > 0 ? 'VISIBLE' : 'NOT FOUND'}`);

// ===== SURFACE 4: Strict Run UI editor (if we created one) =====
if (RUN_ID) {
  await page.goto(`${FRONTEND}/projects/${PROJECT_ID}?tab=runs`);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/07-runs-list.png`, fullPage: true });

  const runRow = page.locator('text=QA Strict Run').first();
  if (await runRow.isVisible({ timeout: 3000 }).catch(() => false)) {
    await runRow.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${OUT}/07b-strict-run-editor.png`, fullPage: true });
    console.log('07: Opened strict run editor');
  }
}

// ===== SURFACE 8: Protocol designation toggle in sidebar (DRAFT protocol) =====
await page.goto(`${FRONTEND}/protocols/${DRAFT_PROTOCOL_ID}`);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(3000);
await page.screenshot({ path: `${OUT}/11-draft-protocol-approved.png`, fullPage: true });
await page.evaluate(() => document.querySelectorAll('aside, .overflow-y-auto').forEach(el => el.scrollTop = el.scrollHeight));
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/11b-sidebar-approved-draft.png`, fullPage: true });

// ===== SECOND VIEWPORT: Portrait tablet 768x1024 =====
await browser.close();
const browser2 = await chromium.launch({ headless: true });
const ctx2 = await browser2.newContext({ viewport: { width: 768, height: 1024 } });
const page2 = await ctx2.newPage();
const errs2 = [];
page2.on('console', msg => { if (msg.type() === 'error') errs2.push(msg.text()); });
page2.on('pageerror', err => errs2.push(`pageerror: ${err.message}`));

await loginUser(page2, 'admin');

// Dashboard portrait
await page2.screenshot({ path: `${OUT}/12-dashboard-portrait.png`, fullPage: true });

// Protocol editor portrait with APPROVED status
await page2.goto(`${FRONTEND}/protocols/${APPROVED_PROTOCOL_ID}`);
await page2.waitForLoadState('networkidle');
await page2.waitForTimeout(3000);
await page2.screenshot({ path: `${OUT}/12b-protocol-portrait.png`, fullPage: true });
await page2.evaluate(() => document.querySelectorAll('aside, .overflow-y-auto').forEach(el => el.scrollTop = el.scrollHeight));
await page2.waitForTimeout(500);
await page2.screenshot({ path: `${OUT}/12c-sidebar-portrait.png`, fullPage: true });

// Org settings portrait
await page2.goto(`${FRONTEND}/settings`);
await page2.waitForLoadState('networkidle');
await page2.waitForTimeout(1500);
await page2.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await page2.screenshot({ path: `${OUT}/12d-org-settings-portrait.png`, fullPage: true });

await browser2.close();

// ===== FINAL REPORT =====
console.log('\n=== FINAL SUMMARY ===');
console.log(`Run gate test: ${gateTestResult}`);
console.log(`Strict run created: RUN_ID=${RUN_ID}, is_strict=${IS_STRICT}`);

console.log('\n=== CONSOLE ERRORS (browser 1, 1024x768) ===');
console.log(JSON.stringify({ consoleErrors }, null, 2));
console.log('\n=== CONSOLE ERRORS (browser 2, 768x1024 portrait) ===');
console.log(JSON.stringify({ errs2 }, null, 2));
