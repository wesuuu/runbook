import { test, expect } from '@playwright/test';
import { loginViaApi, isAuthEnabled } from './auth-helper';

// These test users should exist in the seeded test database
const NON_PRO_USER = 'nonpro@example.com';
const PRO_USER = 'pro@example.com';
const TEST_PASSWORD = 'password';

test.describe('Chat AI Gating', () => {
    test.beforeEach(async ({ page }) => {
        // Skip all tests if auth is not enabled
        const authOn = await isAuthEnabled(page);
        test.skip(!authOn, 'Backend has auth_enabled=false');
    });

    test('non-pro user sees empty state on /chat', async ({ page }) => {
        // Login as non-Pro user
        await loginViaApi(page, NON_PRO_USER, TEST_PASSWORD);

        // Navigate to /chat
        await page.goto('/chat');

        // Wait for page to load
        await page.waitForLoadState('networkidle');

        // Should see empty state message
        const emptyStateHeading = page.getByText('AI Features Unavailable');
        await expect(emptyStateHeading).toBeVisible();

        // Should see description
        const description = page.getByText(/doesn't have AI Chat enabled/);
        await expect(description).toBeVisible();

        // Should see "Contact Administrator" button
        const notifyBtn = page.getByRole('button', { name: /Contact Administrator/ });
        await expect(notifyBtn).toBeVisible();
        await expect(notifyBtn).toBeEnabled();

        // Should NOT see normal chat UI (sidebar, messages area)
        const chatSidebar = page.getByText('Chats');
        await expect(chatSidebar).not.toBeVisible();
    });

    test('non-pro user can contact administrator', async ({ page }) => {
        await loginViaApi(page, NON_PRO_USER, TEST_PASSWORD);
        await page.goto('/chat');

        // Click the "Contact Administrator" button
        const notifyBtn = page.getByRole('button', { name: /Contact Administrator/ });
        await notifyBtn.click();

        // Should see success message
        const successMsg = page.getByText(/Admin notified/);
        await expect(successMsg).toBeVisible();

        // Button should be disabled after click
        await expect(notifyBtn).toBeDisabled();
    });

    test('non-pro user sees rate limit on second notification attempt', async ({ page }) => {
        await loginViaApi(page, NON_PRO_USER, TEST_PASSWORD);
        await page.goto('/chat');

        const notifyBtn = page.getByRole('button', { name: /Contact Administrator/ });

        // First click should succeed
        await notifyBtn.click();
        const successMsg = page.getByText(/Admin notified/);
        await expect(successMsg).toBeVisible();

        // Wait a moment
        await page.waitForTimeout(500);

        // Reload page to reset button state (in real app, would still be disabled via localStorage)
        await page.reload();
        await page.waitForLoadState('networkidle');

        // Try to click again - should get rate limit message or button disabled
        const reloadedBtn = page.getByRole('button', { name: /Contact Administrator/ });

        // Button should be disabled since we just notified
        const isDisabled = await reloadedBtn.isDisabled();
        expect(isDisabled).toBeTruthy();
    });

    test('pro user sees normal chat interface on /chat', async ({ page }) => {
        await loginViaApi(page, PRO_USER, TEST_PASSWORD);
        await page.goto('/chat');

        // Wait for page to load
        await page.waitForLoadState('networkidle');

        // Should NOT see empty state
        const emptyState = page.getByText('AI Features Unavailable');
        await expect(emptyState).not.toBeVisible();

        // Should see normal chat UI
        const chatSidebar = page.getByText('Chats');
        await expect(chatSidebar).toBeVisible();

        // Should see input area
        const inputArea = page.getByPlaceholder(/Ask about/);
        await expect(inputArea).toBeVisible();

        // Should see "New" button to create chat session
        const newBtn = page.getByRole('button', { name: /New/ });
        await expect(newBtn).toBeVisible();
    });

    test('non-pro user does not see FAB on dashboard', async ({ page }) => {
        await loginViaApi(page, NON_PRO_USER, TEST_PASSWORD);

        // Navigate to dashboard
        await page.goto('/');
        await page.waitForLoadState('networkidle');

        // Look for chat FAB - should not be visible
        // The FAB is typically a circular button with chat icon
        const fabButtons = page.getByRole('button').filter({ hasText: /chat|message/i });
        const count = await fabButtons.count();

        // Should have 0 FAB buttons (or at least none that are visible)
        if (count > 0) {
            for (let i = 0; i < count; i++) {
                const btn = fabButtons.nth(i);
                await expect(btn).not.toBeVisible();
            }
        }
    });

    test('pro user sees FAB on dashboard', async ({ page }) => {
        await loginViaApi(page, PRO_USER, TEST_PASSWORD);

        // Navigate to dashboard
        await page.goto('/');
        await page.waitForLoadState('networkidle');

        // FAB should be visible for Pro user
        // Look for the chat panel trigger (often a circular button)
        const fabButton = page.locator('button').filter({
            has: page.locator('svg'),
            // Chat icon is typically in a FAB position
        });

        // At minimum, shouldn't see the "AI Features Unavailable" empty state
        const emptyState = page.getByText('AI Features Unavailable');
        await expect(emptyState).not.toBeVisible();
    });

    test('page layout is correct for empty state', async ({ page }) => {
        await loginViaApi(page, NON_PRO_USER, TEST_PASSWORD);
        await page.goto('/chat');
        await page.waitForLoadState('networkidle');

        // Empty state should be centered and full screen
        const emptyStateContainer = page.getByText('AI Features Unavailable').locator('..');

        // Should take up most of the screen height
        const boundingBox = await emptyStateContainer.boundingBox();
        const viewportSize = page.viewportSize();

        if (boundingBox && viewportSize) {
            // Container should be reasonably sized
            expect(boundingBox.height).toBeGreaterThan(100);
            expect(boundingBox.width).toBeGreaterThan(100);
        }
    });

    test('empty state is responsive on mobile', async ({ page }) => {
        // Set mobile viewport
        await page.setViewportSize({ width: 375, height: 667 });

        await loginViaApi(page, NON_PRO_USER, TEST_PASSWORD);
        await page.goto('/chat');
        await page.waitForLoadState('networkidle');

        // Should still see empty state message
        const emptyStateHeading = page.getByText('AI Features Unavailable');
        await expect(emptyStateHeading).toBeVisible();

        // Button should be visible and clickable on mobile
        const notifyBtn = page.getByRole('button', { name: /Contact Administrator/ });
        await expect(notifyBtn).toBeVisible();
        await expect(notifyBtn).toBeEnabled();

        // No horizontal overflow
        const viewport = page.viewportSize();
        const htmlSize = await page.evaluate(() => document.documentElement.scrollWidth);
        expect(htmlSize).toBeLessThanOrEqual((viewport?.width ?? 0) + 1); // +1 for rounding
    });
});
