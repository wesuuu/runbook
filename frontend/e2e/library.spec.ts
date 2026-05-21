import { test, expect } from '@playwright/test';
import { loginAndNavigate, loginViaApi } from './helpers/auth';
import {
    uploadDocumentViaApi,
    deleteDocumentViaApi,
} from './helpers/library';
import { libraryUrl, libraryDocUrl } from './helpers/slug-urls';

test.describe('Document Library', () => {
    const createdDocumentIds: string[] = [];

    test.afterEach(async ({ page }) => {
        // Cleanup: delete all documents created during the test
        for (const id of createdDocumentIds) {
            try {
                await deleteDocumentViaApi(page, id);
            } catch {
                // Ignore cleanup errors (document may already be deleted)
            }
        }
        createdDocumentIds.length = 0;
    });

    test('library page accessible from nav link', async ({ page }) => {
        await loginAndNavigate(page, 'admin', '/');
        // Click Library in desktop nav
        await page.locator('nav a:has-text("Library")').first().click();
        await page.waitForLoadState('networkidle');
        expect(page.url()).toContain('/library');
    });

    test('shows empty state when no documents', async ({ page }) => {
        await loginViaApi(page, 'admin');
        await page.goto(await libraryUrl(page));
        await page.waitForLoadState('networkidle');
        // Verify empty state text is visible
        const emptyText = page.getByText('Upload your SOPs');
        await expect(emptyText).toBeVisible();
    });

    test('upload text document via dialog', async ({ page }) => {
        await loginViaApi(page, 'admin');
        await page.goto(await libraryUrl(page));
        await page.waitForLoadState('networkidle');

        // Click "Upload Document" button
        await page.getByRole('button', { name: /Upload Document/i }).click();

        // Wait for dialog
        await expect(page.getByText('Add Document')).toBeVisible();

        // Create a test file and attach it
        const buffer = Buffer.from('E2E test document content');
        await page.locator('#file-input').setInputFiles({
            name: 'e2e-test.txt',
            mimeType: 'text/plain',
            buffer,
        });

        // Fill title
        await page.locator('#doc-title').fill('E2E Test Document');

        // Submit
        await page.getByRole('button', { name: /^Upload$/i }).click();

        // Wait for success
        await page.waitForLoadState('networkidle');

        // Verify document appears in list
        await expect(page.getByText('E2E Test Document')).toBeVisible();

        // Track for cleanup
        const link = page.locator('a:has-text("E2E Test Document")').first();
        const href = await link.getAttribute('href');
        if (href) {
            const id = href.split('/').pop();
            if (id) createdDocumentIds.push(id);
        }
    });

    test('document detail shows metadata and reader view', async ({ page }) => {
        await loginViaApi(page, 'admin');
        await page.goto(await libraryUrl(page));
        await page.waitForLoadState('networkidle');

        // Upload via API
        const doc = await uploadDocumentViaApi(page, 'Detail Test Doc');
        createdDocumentIds.push(doc.id);

        // Navigate to detail page
        await page.goto(await libraryDocUrl(page, doc.id));
        await page.waitForLoadState('networkidle');

        // Verify title is visible
        await expect(page.getByText('Detail Test Doc')).toBeVisible();

        // Verify metadata elements
        await expect(page.getByText('TXT')).toBeVisible();
    });

    test('delete document from detail page', async ({ page }) => {
        await loginViaApi(page, 'admin');
        await page.goto(await libraryUrl(page));
        await page.waitForLoadState('networkidle');

        // Upload via API
        const doc = await uploadDocumentViaApi(page, 'Delete Test Doc');

        // Navigate to detail
        await page.goto(await libraryDocUrl(page, doc.id));
        await page.waitForLoadState('networkidle');

        // Click delete button
        await page.getByRole('button', { name: /Delete/i }).first().click();

        // Confirm deletion in dialog
        await page.getByRole('button', { name: /^Delete$/i }).last().click();

        // Wait for redirect to library
        await page.waitForURL('**/library');
        await page.waitForLoadState('networkidle');

        // Verify document is gone
        await expect(page.getByText('Delete Test Doc')).not.toBeVisible();
    });

    test('upload dialog rejects invalid file type', async ({ page }) => {
        await loginViaApi(page, 'admin');
        await page.goto(await libraryUrl(page));
        await page.waitForLoadState('networkidle');

        // Open upload dialog
        await page.getByRole('button', { name: /Upload Document/i }).click();
        await expect(page.getByText('Add Document')).toBeVisible();

        // Try to upload a .exe file
        const buffer = Buffer.from('fake executable');
        await page.locator('#file-input').setInputFiles({
            name: 'malware.exe',
            mimeType: 'application/octet-stream',
            buffer,
        });

        // Verify error message shown
        await expect(page.getByText(/Unsupported file type/i)).toBeVisible();
    });
});
