import { test, expect } from '@playwright/test';

// A syntactically valid UUID that will not exist in the seeded DB.
const MISSING_ID = '00000000-0000-0000-0000-0000000000ff';

test.describe('document refinement route', () => {
    test('renders a graceful error for a missing document', async ({ page }) => {
        // Log in first (mirrors e2e/auth.spec.ts).
        await page.goto('/login');
        await page.fill('#email', 'admin@example.com');
        await page.fill('#password', 'password');
        await page.click('button[type="submit"]');
        await expect(page).not.toHaveURL(/.*login/, { timeout: 15_000 });

        await page.goto(`/library/documents/${MISSING_ID}/refine`);

        // Either the inline ErrorAlert or the back link must be visible —
        // the page must not crash to a blank screen.
        await expect(
            page.getByText(/error/i).or(page.getByText('Back to document')),
        ).toBeVisible({ timeout: 10_000 });
    });
});
