// frontend/qa-verify-driver.mjs
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const FRONTEND = process.env.QA_FRONTEND || 'http://localhost:5173';
const API = process.env.QA_API || 'http://localhost:8000';
const OUT = '/tmp/qa-verify';
mkdirSync(OUT, { recursive: true });

// Non-Pro user: admin@bioprocess.com -> Acme Biologics (essentials tier)
// Pro user: scientist1@bioprocess.com -> BioProcess Inc (pro tier)
const USERS = {
  nonpro: { email: 'admin@bioprocess.com', password: 'password123' },
  pro: { email: 'scientist1@bioprocess.com', password: 'password123' },
};

async function loginAndNavigate(page, userKey, path = '/') {
  const { email, password } = USERS[userKey];
  const res = await page.request.post(`${API}/auth/login`, { data: { email, password } });
  if (!res.ok()) throw new Error(`login failed ${res.status()} for ${email}`);
  const { access_token } = await res.json();
  // Set token on the public /login page so route guard doesn't interfere
  await page.goto(`${FRONTEND}/login`);
  await page.evaluate((t) => localStorage.setItem('auth_token', t), access_token);
  // Now navigate to the target; app's initialize() will pick up the token
  await page.goto(`${FRONTEND}${path}`);
  await page.waitForLoadState('networkidle');
  // Wait for the app to finish initializing (the loading spinner goes away)
  await page.waitForFunction(
    () => !document.querySelector('.min-h-screen.flex.items-center.justify-center') ||
          document.querySelector('nav') !== null,
    { timeout: 10000 }
  ).catch(() => {});
  await page.waitForTimeout(500);
}

const browser = await chromium.launch();
const allErrors = [];

// ============================================================
// SECTION 1: Non-Pro user (admin@bioprocess.com, essentials tier)
// ============================================================
console.log('\n=== Testing NON-PRO user (admin@bioprocess.com / essentials tier) ===');

const ctxNonPro = await browser.newContext({ viewport: { width: 1024, height: 768 } });
const pageNonPro = await ctxNonPro.newPage();
pageNonPro.on('console', (msg) => {
  if (msg.type() === 'error') allErrors.push(`[nonpro] ${msg.text()}`);
});
pageNonPro.on('pageerror', (err) => allErrors.push(`[nonpro pageerror] ${err.message}`));

await loginAndNavigate(pageNonPro, 'nonpro', '/');
await pageNonPro.screenshot({ path: `${OUT}/01-nonpro-dashboard.png`, fullPage: true });
console.log('01: Non-pro dashboard screenshot taken');

// Verify FAB is NOT visible on dashboard
// ChatPanel renders the FAB; when canShowFab is false it's not rendered at all
const chatFabCount = await pageNonPro.locator('button[aria-label="Open chat"], [data-testid="chat-fab"]').count();
console.log('FAB button count on dashboard:', chatFabCount, '(expected: 0 for non-Pro)');

// Also look for any chat floating elements
const chatFloatingCount = await pageNonPro.evaluate(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  const chatBtns = btns.filter(b =>
    b.getAttribute('aria-label')?.toLowerCase().includes('chat') ||
    b.textContent?.toLowerCase().includes('chat')
  );
  return chatBtns.length;
});
console.log('Chat-related buttons on dashboard:', chatFloatingCount);

// Navigate to /chat
await loginAndNavigate(pageNonPro, 'nonproo', '/chat').catch(async () => {
  // Already logged in, just navigate
  await pageNonPro.goto(`${FRONTEND}/chat`);
  await pageNonPro.waitForLoadState('networkidle');
  await pageNonPro.waitForTimeout(800);
});
await pageNonPro.screenshot({ path: `${OUT}/02-nonpro-chat-page.png`, fullPage: true });
console.log('02: Non-pro /chat page screenshot taken');

// Detailed DOM inspection
const chatPageContent = await pageNonPro.evaluate(() => {
  const h2s = Array.from(document.querySelectorAll('h2')).map(h => h.textContent?.trim());
  const btns = Array.from(document.querySelectorAll('button')).map(b => b.textContent?.trim()).filter(Boolean);
  const url = window.location.href;
  return { h2s, btns, url, bodyText: document.body.innerText.slice(0, 500) };
});
console.log('Page URL:', chatPageContent.url);
console.log('H2 headings:', chatPageContent.h2s);
console.log('Buttons:', chatPageContent.btns.slice(0, 10));
console.log('Body text preview:', chatPageContent.bodyText.slice(0, 300));

// Check for "AI Features Unavailable" heading
const heading = await pageNonPro.locator('h2:has-text("AI Features Unavailable")').count();
console.log('AI Features Unavailable heading found:', heading, '(expected: 1)');

// Check "Contact Administrator" button
const contactBtn = pageNonPro.locator('button:has-text("Contact Administrator")');
const contactBtnCount = await contactBtn.count();
console.log('Contact Administrator button count:', contactBtnCount, '(expected: 1)');

if (contactBtnCount > 0) {
  const btnEnabled = await contactBtn.isEnabled();
  console.log('Contact Administrator button enabled before click:', btnEnabled, '(expected: true)');

  // Click it
  await contactBtn.click();
  await pageNonPro.waitForTimeout(2500);
  await pageNonPro.screenshot({ path: `${OUT}/03-nonpro-after-notify.png`, fullPage: true });
  console.log('03: Non-pro after clicking Contact Admin screenshot taken');

  const successMsg = await pageNonPro.locator('text=/Admin notified/i').count();
  console.log('Success message visible:', successMsg, '(expected: 1)');

  const btnDisabledAfterClick = await contactBtn.isDisabled();
  console.log('Button disabled after click:', btnDisabledAfterClick, '(expected: true)');
}

// ============================================================
// SECTION 2: Mobile viewport - non-pro
// ============================================================
console.log('\n=== Mobile viewport (375x667) - Non-Pro ===');
const ctxMobile = await browser.newContext({ viewport: { width: 375, height: 667 } });
const pageMobile = await ctxMobile.newPage();
pageMobile.on('console', (msg) => {
  if (msg.type() === 'error') allErrors.push(`[mobile] ${msg.text()}`);
});

await loginAndNavigate(pageMobile, 'nonpro', '/chat');
await pageMobile.screenshot({ path: `${OUT}/04-nonpro-mobile-chat.png`, fullPage: true });
console.log('04: Mobile /chat screenshot taken');

const mobileOverflow = await pageMobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
console.log('Mobile horizontal overflow:', mobileOverflow, '(expected: false)');
const mobileHeading = await pageMobile.locator('h2:has-text("AI Features Unavailable")').count();
console.log('Mobile: AI Features Unavailable heading:', mobileHeading, '(expected: 1)');
const mobileContact = await pageMobile.locator('button:has-text("Contact Administrator")').count();
console.log('Mobile: Contact Administrator button:', mobileContact, '(expected: 1)');

await ctxMobile.close();

// ============================================================
// SECTION 3: Pro user
// ============================================================
console.log('\n=== Testing PRO user (scientist1@bioprocess.com / pro tier) ===');

const ctxPro = await browser.newContext({ viewport: { width: 1024, height: 768 } });
const pagePro = await ctxPro.newPage();
pagePro.on('console', (msg) => {
  if (msg.type() === 'error') allErrors.push(`[pro] ${msg.text()}`);
});
pagePro.on('pageerror', (err) => allErrors.push(`[pro pageerror] ${err.message}`));

await loginAndNavigate(pagePro, 'pro', '/');
await pagePro.waitForTimeout(1000);
await pagePro.screenshot({ path: `${OUT}/05-pro-dashboard.png`, fullPage: true });
console.log('05: Pro dashboard screenshot taken');

// Look at all floating/fixed buttons
const proFloatingButtons = await pagePro.evaluate(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  return btns
    .filter(b => {
      const style = window.getComputedStyle(b);
      return style.position === 'fixed' || b.getAttribute('aria-label')?.toLowerCase().includes('chat');
    })
    .map(b => ({
      text: b.textContent?.trim(),
      ariaLabel: b.getAttribute('aria-label'),
      position: window.getComputedStyle(b).position,
      visible: b.offsetWidth > 0,
    }));
});
console.log('Pro: Fixed/chat buttons on dashboard:', proFloatingButtons);

// Navigate to /chat as Pro
await pagePro.goto(`${FRONTEND}/chat`);
await pagePro.waitForLoadState('networkidle');
await pagePro.waitForTimeout(800);
await pagePro.screenshot({ path: `${OUT}/06-pro-chat-page.png`, fullPage: true });
console.log('06: Pro /chat page screenshot taken');

const proPageContent = await pagePro.evaluate(() => {
  const h2s = Array.from(document.querySelectorAll('h2')).map(h => h.textContent?.trim());
  const btns = Array.from(document.querySelectorAll('button')).map(b => b.textContent?.trim()).filter(Boolean);
  return { h2s, btns };
});
console.log('Pro /chat H2 headings:', proPageContent.h2s);
console.log('Pro /chat buttons:', proPageContent.btns.slice(0, 15));

const nonProHeading = await pagePro.locator('h2:has-text("AI Features Unavailable")').count();
console.log('Pro user: "AI Features Unavailable" heading:', nonProHeading, '(expected: 0)');

const chatsHeading = await pagePro.locator('h2:has-text("Chats")').count();
console.log('Pro user: "Chats" sidebar heading count:', chatsHeading, '(expected: 1)');

const newChatBtn = await pagePro.locator('button:has-text("New"), button:has-text("+ New")').count();
console.log('Pro user: New chat button count:', newChatBtn, '(expected: 1)');

// ============================================================
// SECTION 4: API endpoint test
// ============================================================
console.log('\n=== API endpoint test: /chat/notify-admin ===');

// Get fresh nonpro token for direct API test
const nonproLoginRes = await pagePro.request.post(`${API}/auth/login`, {
  data: { email: USERS.nonpro.email, password: USERS.nonproo?.password || 'password123' }
});
if (nonproLoginRes.ok()) {
  const { access_token } = await nonproLoginRes.json();
  const headers = { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json' };
  // First call (may get 200 or 429 depending on previous test)
  const res1 = await pagePro.request.post(`${API}/chat/notify-admin`, { headers, data: {} });
  console.log('Notify-admin call 1 status:', res1.status(), '(expected 200 or 429)');
  // Second call should be 429
  const res2 = await pagePro.request.post(`${API}/chat/notify-admin`, { headers, data: {} });
  console.log('Notify-admin call 2 status:', res2.status(), '(expected 429 due to rate limit)');
} else {
  console.log('Could not get nonpro token for API test, status:', nonproLoginRes.status());
}

// ============================================================
// SECTION 5: Console errors summary
// ============================================================
console.log('\n=== Console errors ===');
const relevantErrors = allErrors.filter(e =>
  !e.includes('ERR_CONNECTION_REFUSED') &&  // ignore benign failed requests
  !e.includes('beforeunload')
);
console.log('Relevant errors:', relevantErrors.length);
if (relevantErrors.length > 0) {
  console.log(JSON.stringify(relevantErrors, null, 2));
}
console.log('All errors count (including network):', allErrors.length);

await browser.close();
console.log('\nScreenshots saved to /tmp/qa-verify/');
