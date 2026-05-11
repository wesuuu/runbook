// qa-verify-drag-test.mjs — targeted drag test on APPROVED protocol
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const FRONTEND = 'http://localhost:5183';
const API = 'http://localhost:8010';
const OUT = '/tmp/qa-drag';
mkdirSync(OUT, { recursive: true });

// The APPROVED Skin Cell Seeding Protocol
const APPROVED_PROTOCOL_ID = 'f0c004e5-7dca-44f5-b256-a7287f3c57ef';

async function login(page) {
  const res = await page.request.post(`${API}/auth/login`, {
    data: { email: 'admin@bioprocess.com', password: 'password123' }
  });
  const { access_token } = await res.json();
  await page.goto(`${FRONTEND}/`);
  await page.evaluate((t) => localStorage.setItem('auth_token', t), access_token);
  await page.goto(`${FRONTEND}/`);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  return access_token;
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1024, height: 768 } });
const page = await context.newPage();

const consoleErrors = [];
page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(msg.text());
  if (msg.type() === 'log' && msg.text().includes('APPROVED')) console.log('LOG:', msg.text());
});
page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));

const token = await login(page);

// Verify protocol is APPROVED
const statusRes = await page.request.get(`${API}/science/protocols/${APPROVED_PROTOCOL_ID}`, {
  headers: { 'Authorization': `Bearer ${token}` }
});
const proto = await statusRes.json();
console.log(`Protocol: ${proto.name}, status: ${proto.status}`);

// Navigate to the approved protocol
await page.goto(`${FRONTEND}/protocols/${APPROVED_PROTOCOL_ID}`);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(4000);
await page.screenshot({ path: `${OUT}/01-approved-protocol.png`, fullPage: true });

// Check status badge/header
const headerText = await page.locator('header, .toolbar, [class*="toolbar"], h1, h2').allTextContents();
console.log('Header text:', headerText.slice(0, 5));

const flowNodes = await page.locator('.svelte-flow__node').all();
console.log(`Canvas nodes: ${flowNodes.length}`);

// Find a unit op node (not a swimlane/group/processStart)
let targetNode = null;
for (const n of flowNodes) {
  const cls = await n.getAttribute('class') || '';
  // Only unitOp nodes — skip swimlanes and processStart
  if (cls.includes('svelte-flow__node-unitOp')) {
    const box = await n.boundingBox();
    if (box && box.width > 20 && box.height > 20) {
      targetNode = n;
      break;
    }
  }
}

if (!targetNode) {
  console.log('No unitOp node found — listing all node classes:');
  for (const n of flowNodes) {
    const cls = await n.getAttribute('class') || '';
    const box = await n.boundingBox();
    console.log(`  cls="${cls.split(' ').filter(c => c.startsWith('svelte')).join(' ')}" box=${JSON.stringify(box)}`);
  }
}

if (targetNode) {
  const box = await targetNode.boundingBox();
  const nodeClass = await targetNode.getAttribute('class') || '';
  console.log(`Dragging node: class="${nodeClass.split(' ').filter(c => c.startsWith('svelte')).join(' ')}" at (${box.x.toFixed(0)}, ${box.y.toFixed(0)}), size=${box.width.toFixed(0)}x${box.height.toFixed(0)}`);

  // Perform a deliberate drag
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;

  await page.mouse.move(cx, cy);
  await page.waitForTimeout(100);
  await page.mouse.down();
  await page.waitForTimeout(200);
  // Move in steps to simulate real drag
  for (let i = 1; i <= 10; i++) {
    await page.mouse.move(cx + i * 8, cy + i * 5, { steps: 1 });
    await page.waitForTimeout(30);
  }
  await page.waitForTimeout(300);
  await page.mouse.up();
  await page.waitForTimeout(2500);

  await page.screenshot({ path: `${OUT}/02-after-drag.png`, fullPage: true });

  const dialogs = await page.locator('[role="dialog"]').all();
  console.log(`Dialogs visible after drag: ${dialogs.length}`);

  if (dialogs.length > 0) {
    const dialogText = await dialogs[0].textContent();
    console.log(`Dialog text: "${dialogText?.substring(0, 200)}"`);
    await page.screenshot({ path: `${OUT}/03-revert-dialog.png`, fullPage: true });

    // Test Cancel path
    const cancelBtn = page.locator('[role="dialog"] button').filter({ hasText: /cancel/i }).first();
    if (await cancelBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log('Clicking Cancel...');
      await cancelBtn.click();
      await page.waitForTimeout(1000);
      await page.screenshot({ path: `${OUT}/04-after-cancel.png`, fullPage: true });
      console.log('PASS: Cancel clicked — node should be back in original position, status still APPROVED');
    }

    // Test Confirm path — drag again
    console.log('\nTesting confirm path (drag again)...');
    const box2 = await targetNode.boundingBox();
    if (box2) {
      const cx2 = box2.x + box2.width / 2;
      const cy2 = box2.y + box2.height / 2;
      await page.mouse.move(cx2, cy2);
      await page.mouse.down();
      await page.waitForTimeout(200);
      for (let i = 1; i <= 10; i++) {
        await page.mouse.move(cx2 + i * 8, cy2 + i * 5, { steps: 1 });
        await page.waitForTimeout(30);
      }
      await page.mouse.up();
      await page.waitForTimeout(2500);

      const dialogs2 = await page.locator('[role="dialog"]').all();
      console.log(`Dialogs on second drag: ${dialogs2.length}`);
      if (dialogs2.length > 0) {
        // Find the confirm button
        const allBtns = await page.locator('[role="dialog"] button').all();
        console.log('Dialog buttons:');
        for (const b of allBtns) {
          const txt = await b.textContent();
          const enabled = await b.isEnabled();
          console.log(`  "${txt}" enabled=${enabled}`);
        }
        const confirmBtn = page.locator('[role="dialog"] button').filter({ hasText: /continue|confirm|proceed|edit|yes|ok/i }).first();
        if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await confirmBtn.click();
          await page.waitForTimeout(1000);
          console.log('PASS: Confirmed edit — status should revert to DRAFT on save');
          await page.screenshot({ path: `${OUT}/05-after-confirm.png`, fullPage: true });
        }
      }
    }
  } else {
    // Check what happened
    const toasts = await page.locator('[data-sonner-toast]').allTextContents();
    console.log('FAIL: No dialog appeared after drag. Toasts:', toasts);
    // Check current page URL / protocol status
    const statusRes2 = await page.request.get(`${API}/science/protocols/${APPROVED_PROTOCOL_ID}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const proto2 = await statusRes2.json();
    console.log(`Protocol status after drag: ${proto2.status}`);
  }
} else {
  console.log('No suitable node found for drag test');
  await page.screenshot({ path: `${OUT}/02-no-nodes.png`, fullPage: true });
}

console.log('\nConsole errors:', JSON.stringify(consoleErrors, null, 2));
await browser.close();
