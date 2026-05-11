// qa-drag-fix-test.mjs — test drag guard on APPROVED protocol 9b007093
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const FRONTEND = 'http://localhost:5183';
const API = 'http://localhost:8010';
const OUT = '/tmp/qa-drag-fix';
mkdirSync(OUT, { recursive: true });

// Untitled Protocol — confirmed APPROVED with 3 unitOps
const APPROVED_PROTOCOL_ID = '9b007093-b131-441f-959b-2207ae05f2ab';

async function login(page) {
  const res = await page.request.post(`${API}/auth/login`, {
    data: { email: 'admin@bioprocess.com', password: 'password123' }
  });
  const { access_token } = await res.json();
  await page.goto(`${FRONTEND}/`);
  await page.evaluate((t) => localStorage.setItem('auth_token', t), access_token);
  await page.goto(`${FRONTEND}/`);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1000);
  return access_token;
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();

const consoleErrors = [];
const consoleLogs = [];
page.on('console', (msg) => {
  const text = msg.text();
  if (msg.type() === 'error') consoleErrors.push(text);
  if (text.includes('[QAD]') || text.includes('revertOnEdit') || text.includes('APPROVED')) {
    console.log(`[BROWSER ${msg.type().toUpperCase()}]:`, text);
    consoleLogs.push(text);
  }
});
page.on('pageerror', (err) => {
  console.log('PAGEERROR:', err.message);
  consoleErrors.push(`pageerror: ${err.message}`);
});

const token = await login(page);

// Verify protocol status
const statusRes = await page.request.get(`${API}/science/protocols/${APPROVED_PROTOCOL_ID}`, {
  headers: { 'Authorization': `Bearer ${token}` }
});
const proto = await statusRes.json();
console.log(`Protocol: "${proto.name}", status: ${proto.status}`);
if (proto.status !== 'APPROVED') {
  console.log('ERROR: Protocol is not APPROVED!');
  await browser.close();
  process.exit(1);
}

// Navigate to the approved protocol
await page.goto(`${FRONTEND}/protocols/${APPROVED_PROTOCOL_ID}`);
await page.waitForLoadState('networkidle');
// Wait for canvas to fully render
await page.waitForTimeout(5000);
await page.screenshot({ path: `${OUT}/01-initial.png`, fullPage: true });
console.log('Screenshot 01 taken — initial load');

// Get canvas bounding box to understand the layout
const canvasBox = await page.locator('.svelte-flow__pane').first().boundingBox();
console.log('Canvas box:', JSON.stringify(canvasBox));

// List all nodes
const allNodes = await page.locator('.svelte-flow__node').all();
console.log(`Total canvas nodes: ${allNodes.length}`);

for (const n of allNodes) {
  const cls = await n.getAttribute('class') || '';
  const box = await n.boundingBox();
  const short = cls.split(' ').filter(c => c.startsWith('svelte-flow__node')).join(' ');
  console.log(`  ${short} @ x=${box?.x?.toFixed(0)} y=${box?.y?.toFixed(0)} w=${box?.width?.toFixed(0)} h=${box?.height?.toFixed(0)}`);
}

// Find a unitOp node that is NOT behind the sidebar (x > 300) and visible
const unitOpNodes = await page.locator('.svelte-flow__node-unitOp').all();
console.log(`UnitOp nodes: ${unitOpNodes.length}`);

let targetNode = null;
let targetBox = null;
for (const n of unitOpNodes) {
  const box = await n.boundingBox();
  if (box && box.x > 300 && box.width > 20 && box.height > 20) {
    // Check it's within the visible canvas (not hidden)
    if (box.y > 50 && box.y < 850) {
      targetNode = n;
      targetBox = box;
      console.log(`Selected target node @ x=${box.x.toFixed(0)}, y=${box.y.toFixed(0)}, w=${box.width.toFixed(0)}, h=${box.height.toFixed(0)}`);
      break;
    }
  }
}

if (!targetNode) {
  console.log('FAIL: No suitable unitOp node found in visible canvas area');
  await page.screenshot({ path: `${OUT}/02-no-target.png`, fullPage: true });
  await browser.close();
  process.exit(1);
}

// Perform drag
const cx = targetBox.x + targetBox.width / 2;
const cy = targetBox.y + targetBox.height / 2;
console.log(`Dragging from center (${cx.toFixed(0)}, ${cy.toFixed(0)})`);

await page.mouse.move(cx, cy);
await page.waitForTimeout(100);
await page.mouse.down();
await page.waitForTimeout(200);

// Drag 100px right and 50px down in steps
for (let i = 1; i <= 20; i++) {
  await page.mouse.move(cx + i * 5, cy + i * 2.5, { steps: 1 });
  await page.waitForTimeout(20);
}
await page.waitForTimeout(200);
await page.mouse.up();
console.log('Drag complete — waiting for dialog...');
await page.waitForTimeout(3000);

await page.screenshot({ path: `${OUT}/02-after-drag.png`, fullPage: true });

// Check dialog in DOM (even if hidden)
const dialogCount = await page.locator('[role="dialog"]').count();
const dialogVisible = await page.locator('[role="dialog"]').isVisible().catch(() => false);
console.log(`Dialog count in DOM: ${dialogCount}, visible: ${dialogVisible}`);

// Check revertOnEditDialogOpen state via page evaluate
const dialogOpenState = await page.evaluate(() => {
  // Check all dialog portals in the body
  const allDialogs = document.querySelectorAll('[role="dialog"]');
  const allPortals = document.querySelectorAll('[data-portal], [data-bits-portal]');
  return {
    dialogCount: allDialogs.length,
    portalCount: allPortals.length,
    bodyChildren: document.body.children.length,
    allDialogHidden: Array.from(allDialogs).map(d => ({
      hidden: d.hidden,
      display: getComputedStyle(d).display,
      visibility: getComputedStyle(d).visibility,
      ariaHidden: d.getAttribute('aria-hidden'),
    }))
  };
});
console.log('DOM dialog state:', JSON.stringify(dialogOpenState, null, 2));

if (dialogVisible) {
  const dialogText = await page.locator('[role="dialog"]').textContent();
  console.log(`Dialog text: "${dialogText?.substring(0, 200)}"`);
  await page.screenshot({ path: `${OUT}/03-dialog.png`, fullPage: true });
  console.log('PASS: Dialog appeared correctly');

  // Test Cancel
  const cancelBtn = page.locator('[role="dialog"] button').filter({ hasText: /cancel/i }).first();
  if (await cancelBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    await cancelBtn.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${OUT}/04-after-cancel.png`, fullPage: true });
    console.log('PASS: Cancel clicked successfully');
  }
} else {
  // Check toasts and console logs for clues
  const toasts = await page.locator('[data-sonner-toast]').allTextContents();
  console.log('FAIL: No dialog appeared. Toasts:', toasts);
  console.log('Console logs captured:', consoleLogs);

  // Check if any state was changed — look for revert-related indicators
  const statusAfter = await page.request.get(`${API}/science/protocols/${APPROVED_PROTOCOL_ID}`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  const protoAfter = await statusAfter.json();
  console.log(`Protocol status after drag: ${protoAfter.status}`);
}

// Test via keyboard/menu path (the requireEditConfirmation route that DOES work)
// Click a unit op to select, then try to edit via Inspector
console.log('\n--- Testing requireEditConfirmation via sidebar edit ---');
await page.mouse.click(cx, cy);
await page.waitForTimeout(1000);
await page.screenshot({ path: `${OUT}/05-after-click.png`, fullPage: true });

// Check if Inspector is visible
const inspectorVisible = await page.locator('[data-inspector], .inspector, text="Parameters"').isVisible().catch(() => false);
console.log(`Inspector visible: ${inspectorVisible}`);

// Also test node delete via context menu (confirmed working path)
console.log('\n--- Testing context menu delete guard ---');
await page.mouse.click(cx, cy, { button: 'right' });
await page.waitForTimeout(500);
const contextMenu = await page.locator('[role="menu"]').isVisible().catch(() => false);
console.log(`Context menu visible: ${contextMenu}`);
if (contextMenu) {
  await page.screenshot({ path: `${OUT}/06-context-menu.png`, fullPage: true });
  // Look for delete option
  const deleteOpt = page.locator('[role="menu"] [role="menuitem"]').filter({ hasText: /delete|remove/i }).first();
  if (await deleteOpt.isVisible({ timeout: 1000 }).catch(() => false)) {
    await deleteOpt.click();
    await page.waitForTimeout(1000);
    const dialogAfterMenu = await page.locator('[role="dialog"]').isVisible().catch(() => false);
    console.log(`Dialog after context-menu delete: ${dialogAfterMenu}`);
    if (dialogAfterMenu) {
      const txt = await page.locator('[role="dialog"]').textContent();
      console.log(`Dialog text: "${txt?.substring(0, 150)}"`);
      await page.screenshot({ path: `${OUT}/07-context-menu-dialog.png`, fullPage: true });
      // Cancel to not actually delete
      const cancelBtn2 = page.locator('[role="dialog"] button').filter({ hasText: /cancel/i }).first();
      if (await cancelBtn2.isVisible({ timeout: 1000 }).catch(() => false)) {
        await cancelBtn2.click();
        await page.waitForTimeout(500);
      }
    }
  }
}

console.log('\n=== Console errors:', JSON.stringify(consoleErrors, null, 2));
await browser.close();
